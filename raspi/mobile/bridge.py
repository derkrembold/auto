"""Sole mobile IPC client. No direct LIN access; simulation never opens a socket."""
import re
import math
import socket
import time
from multiprocessing.connection import Connection

from control_core import FAULT, ERR_UNREACHABLE, ERR_MOTOR_STALLED

# A powered-off STM32 answers `status` only after the watchdog's ~2 s LIN timeout.
PROBE_TIMEOUT_S = 3.0
PROBE_INTERVAL_S = 2.0
COMMAND_TIMEOUT_S = 0.5


class Unreachable(RuntimeError):
    """Motor controller, current sensor or watchdog does not answer (e.g. fuse off).

    stale=True: a reply may still arrive later, so the connection must be reopened
    before the next command, or that late reply would be read as the next answer.
    """
    def __init__(self, message, stale=False):
        super().__init__(message)
        self.stale = stale


class MotorFault(RuntimeError):
    """Firmware reports a latched sys_error, e.g. STALL_TIM_ERR: no rotation."""
    def __init__(self, motor, reply):
        super().__init__("Motor fault or unreadable status: %s" % reply)
        self.motor = motor


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
        except OSError as exc:
            sock.close()
            raise Unreachable("Watchdog socket unavailable: %s" % exc)

    def command(self, text, timeout=COMMAND_TIMEOUT_S):
        self.connection.send(text)
        if not self.connection.poll(timeout):
            raise Unreachable("Watchdog did not answer '%s' within %.1f s" % (text, timeout), stale=True)
        reply = self.connection.recv()
        if not isinstance(reply, str) or not reply.startswith("OK"):
            raise RuntimeError("Watchdog rejected command: %s" % reply)
        return reply

    def check_status(self, motor, timeout=COMMAND_TIMEOUT_S):
        reply = self.command("status %d" % motor, timeout)
        ret = re.search(r"\bret=(-?\d+)", reply)
        sys_error = re.search(r"\bsys_error=(-?\d+)", reply)
        if ret is None or ret.group(1) != "0":
            raise Unreachable("Motor %d not reachable: %s" % (motor, reply))
        if sys_error is None or sys_error.group(1) != "0":
            raise MotorFault(motor, reply)

    def reset(self, motor):
        # Clears the latched firmware error; the setpoint becomes zero, nothing moves.
        self.command("reset %d" % motor)

    def speeds(self, values):
        for motor, speed in zip((self.config.left, self.config.right), values):
            self.command("speed %d %d" % (motor, speed))

    def check_current(self, timeout=COMMAND_TIMEOUT_S):
        reply = self.command("current 0", timeout)
        fields = dict(re.findall(r"(ret|val1|val2)=([^ ]+)", reply))
        if fields.get("ret") != "0":
            raise Unreachable("Current sensor not reachable: %s" % reply)
        for channel in ("val1", "val2"):
            amps = float(fields[channel])
            if not math.isfinite(amps) or abs(amps) > 15:
                raise RuntimeError("Overcurrent or invalid current measurement")

    def close(self):
        if self.connection is not None:
            self.connection.close()  # watchdog's existing stop-all-on-disconnect
            self.connection = None


def _probe(client, motors):
    """Zero both setpoints, then require every device to answer cleanly."""
    client.connect()
    client.speeds((0, 0))
    for motor in motors:
        client.check_status(motor, PROBE_TIMEOUT_S)
    client.check_current(PROBE_TIMEOUT_S)


def worker(control, lock, shutdown, log, client=None, clock=time.monotonic):
    live = control.config.live
    if live and client is None:
        client = WatchdogClient(control.config)
    motors = (control.config.left, control.config.right)
    next_probe = 0.0
    reported = None

    def unavailable(exc, code):
        nonlocal reported
        if getattr(exc, "stale", False):
            client.close()
        with lock:
            control.unavailable(code)
        if str(exc) != reported:
            log.warning("Driving blocked until devices answer again: %s", exc)
            reported = str(exc)

    def zero_quietly():
        if client.connection is None:
            return  # closed: the watchdog has already stopped all motors
        try:
            client.speeds((0, 0))
        except Exception:
            client.close()  # the watchdog stops all motors on disconnect

    try:
        while not shutdown.wait(0.1):
            with lock:
                values = control.tick()
                faulted = control.state == FAULT
                ready = control.ready
            if not live:
                continue
            if faulted:
                client.close()
                break
            if not ready:
                # Fuse off / controller unpowered: retry until it answers, then re-enable Start.
                if clock() < next_probe:
                    continue
                next_probe = clock() + PROBE_INTERVAL_S
                try:
                    _probe(client, motors)
                except Unreachable as exc:
                    unavailable(exc, ERR_UNREACHABLE)
                    continue
                except MotorFault as exc:
                    # Latched stall (e.g. no motor power): clear it at zero speed, re-check next round.
                    unavailable(exc, ERR_MOTOR_STALLED)
                    try:
                        client.reset(exc.motor)
                    except Unreachable as lost:
                        unavailable(lost, ERR_UNREACHABLE)
                    next_probe = clock() + 0.5
                    continue
                with lock:
                    control.available()
                log.info("Motors and current sensor answer; Start enabled")
                reported = None
                continue
            try:
                # Check latched STM32 faults before every speed batch, avoiding re-arm loops.
                for motor in motors:
                    client.check_status(motor)
                client.check_current()
                with lock:
                    # Recompute after potentially slow I/O; never send a stale queued target.
                    values = control.tick()
                client.speeds(values)
            except Unreachable as exc:
                unavailable(exc, ERR_UNREACHABLE)
                zero_quietly()
                next_probe = clock() + PROBE_INTERVAL_S
            except MotorFault as exc:
                unavailable(exc, ERR_MOTOR_STALLED)
                zero_quietly()
                next_probe = 0.0
    except Exception:
        log.exception("Mobile control stopped: watchdog or motor unavailable")
        with lock:
            control.ready = False
            control.fault()
    finally:
        if client:
            client.close()
