"""Sole mobile IPC client. No direct LIN access; simulation never opens a socket."""
import re
import math
import socket
import time
from multiprocessing.connection import Connection


class WatchdogClient:
    def __init__(self, config):
        self.config = config
        self.connection = None

    def connect(self):
        if self.connection is not None:
            return
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(0.5)
            sock.connect(self.config.socket_path)
            sock.setblocking(True)
            self.connection = Connection(sock.detach())
            for motor in (self.config.left, self.config.right):
                self.check_status(motor)
        except Exception:
            sock.close()
            self.close()
            raise

    def command(self, text):
        self.connection.send(text)
        if not self.connection.poll(0.5):
            raise TimeoutError("Watchdog did not acknowledge within 500 ms")
        reply = self.connection.recv()
        if not isinstance(reply, str) or not reply.startswith("OK"):
            raise RuntimeError("Watchdog rejected command: %s" % reply)
        return reply

    def check_status(self, motor):
        reply = self.command("status %d" % motor)
        if not re.search(r"\bret=0\b", reply) or not re.search(r"\bsys_error=0\b", reply):
            raise RuntimeError("Motor fault or unreadable status: %s" % reply)

    def speeds(self, values):
        for motor, speed in zip((self.config.left, self.config.right), values):
            self.command("speed %d %d" % (motor, speed))

    def check_current(self):
        reply = self.command("current 0")
        fields = dict(re.findall(r"(ret|val1|val2)=([^ ]+)", reply))
        if fields.get("ret") != "0":
            raise RuntimeError("Current sensor unavailable")
        for channel in ("val1", "val2"):
            amps = float(fields[channel])
            if not math.isfinite(amps) or abs(amps) > 15:
                raise RuntimeError("Overcurrent or invalid current measurement")

    def close(self):
        if self.connection is not None:
            self.connection.close()  # watchdog's existing stop-all-on-disconnect
            self.connection = None


def worker(control, lock, shutdown, log):
    client = WatchdogClient(control.config) if control.config.live else None
    try:
        if client:
            # Explicit --live only. Fail closed if another client owns the watchdog.
            client.connect()
            client.speeds((0, 0))
            with lock:
                control.ready = True
        while not shutdown.wait(0.1):
            with lock:
                values = control.tick()
                faulted = control.state == 3
            if client:
                if faulted:
                    client.close()
                    break
                # Check latched STM32 faults before every speed batch, avoiding re-arm loops.
                for motor in (control.config.left, control.config.right):
                    client.check_status(motor)
                client.check_current()
                with lock:
                    # Recompute after potentially slow I/O; never send a stale queued target.
                    values = control.tick()
                client.speeds(values)
    except Exception:
        log.exception("Mobile control stopped: watchdog or motor unavailable")
        with lock:
            control.ready = False
            control.fault()
    finally:
        if client:
            client.close()
