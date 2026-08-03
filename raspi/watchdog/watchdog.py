import sys
import threading
import time
from multiprocessing.connection import Listener

import linbus

# Must match motorcontrol.py's SOCKET_ADDRESS.
SOCKET_ADDRESS = '/tmp/motorwatchdog.sock'

KNOWN_COMMANDS = {"speed", "on", "off", "hal", "rpm", "temp"}

# Business/safety speed limit — separate from the protocol-level int16
# range linbus.set_speed() clamps to. Deliberately below the motor's
# physical ceiling (~2700-4050 rpm depending on voltage, see
# STM32/notes.md — itself flagged as possibly outdated) until the
# speed-really-means-rpm assumption is validated (see root CLAUDE.md's
# Open Points).
SPEED_MIN = -3000
SPEED_MAX = 3000

# `motorcontrol.py` holds one persistent connection for its whole
# session — a closed connection is detected immediately (EOFError) and
# stops the motor right away, no timeout needed for that case. This
# timeout instead covers "connection still open, but nothing sent in a
# while" (e.g. a hung supervisor that hasn't crashed outright).
IDLE_TIMEOUT = 20.0

# How often the watchdog polls `rpm` itself — independent of whether
# any client is even connected. This is what feeds the stall check
# below; it does not depend on a client asking for `rpm`.
RPM_POLL_INTERVAL = 1.0

# Grace period after a 0 -> nonzero speed command during which rpm==0 is
# NOT treated as stall evidence (startup torque/static friction delay).
STALL_GRACE_PERIOD = 3.0

SPINNER_CHARS = "-\\|/"


def validate(command):
    parts = command.split()
    if not parts:
        return False, "empty command"

    verb = parts[0]
    if verb not in KNOWN_COMMANDS:
        return False, f"unknown command: {verb}"

    if verb == "speed":
        if len(parts) != 2:
            return False, "usage: speed <value>"
        try:
            value = int(parts[1])
        except ValueError:
            return False, "speed value must be an integer"
        if not (SPEED_MIN <= value <= SPEED_MAX):
            return False, f"speed value out of range ({SPEED_MIN}..{SPEED_MAX})"
    elif len(parts) != 1:
        return False, f"usage: {verb}"

    return True, None


class Watchdog:
    # Owns the bus connection (real or dry-run) and all safety state.
    # `execute()` is called from the main accept loop (one client
    # connection at a time); `monitor()` runs in its own background
    # thread and self-polls `rpm` plus checks connection idle time —
    # `lock` guards every `lin` access so the two never write
    # interleaved bytes onto the same connection. See
    # raspi/watchdog/CLAUDE.md's "Two-Layer Safety Check" section.

    def __init__(self, lin):
        self.lin = lin
        self.lock = threading.Lock()

        # None = no client currently connected.
        self.last_command_time = None
        self.stopped_for_idle = False
        self.spinner_index = 0

        # Interim rpm-only stall check (lower layer). Upper layer
        # (current sensor) not built yet — sensor hardware isn't
        # operational yet, see currentsensor/CLAUDE.md.
        self.last_commanded_speed = 0
        self.speed_became_nonzero_at = None

    def _advance_spinner(self):
        char = SPINNER_CHARS[self.spinner_index % len(SPINNER_CHARS)]
        self.spinner_index += 1
        print(f"\rwatchdog: {char}  ", end="", flush=True)

    def _stop_motor(self, reason):
        print(f"\nwatchdog: {reason} — stopping motor")
        with self.lock:
            linbus.set_speed(self.lin, 0)
        self.last_commanded_speed = 0
        self.speed_became_nonzero_at = None

    def on_connect(self):
        self.last_command_time = time.monotonic()
        self.stopped_for_idle = False

    def on_disconnect(self):
        self._stop_motor("client disconnected")
        self.last_command_time = None

    def _check_stall(self, rpm_value):
        if self.last_commanded_speed == 0 or self.speed_became_nonzero_at is None:
            return
        if time.monotonic() - self.speed_became_nonzero_at < STALL_GRACE_PERIOD:
            return  # still in startup grace period, don't judge yet
        if rpm_value == 0:
            self._stop_motor(f"STALL suspected — commanded speed="
                              f"{self.last_commanded_speed} but rpm=0")

    def _dispatch(self, verb, parts):
        # Must be called with self.lock held.
        if verb == "speed":
            value = int(parts[1])
            linbus.set_speed(self.lin, value)
            if self.last_commanded_speed == 0 and value != 0:
                self.speed_became_nonzero_at = time.monotonic()
            elif value == 0:
                self.speed_became_nonzero_at = None
            self.last_commanded_speed = value
            return "OK"
        if verb == "on":
            linbus.led_on(self.lin)
            return "OK"
        if verb == "off":
            linbus.led_off(self.lin)
            return "OK"
        if verb == "hal":
            ret, data = linbus.get_hal(self.lin)
            return f"OK ret={ret} data={[linbus.hexbyte(b) for b in data]}"
        if verb == "rpm":
            ret, value = linbus.get_rpm(self.lin)
            hex_value = linbus.hexword(value) if value is not None else None
            return f"OK ret={ret} rpm={value} (hex={hex_value})"
        if verb == "temp":
            ret, value = linbus.get_temp(self.lin)
            hex_value = linbus.hexword(value) if value is not None else None
            return f"OK ret={ret} temp={value} (hex={hex_value})"
        return f"ERR unhandled command: {verb}"  # unreachable if validate() is correct

    def execute(self, command):
        ok, error = validate(command)
        if not ok:
            return f"ERR {error}"

        self.last_command_time = time.monotonic()
        self._advance_spinner()

        parts = command.split()
        with self.lock:
            return self._dispatch(parts[0], parts)

    def check_idle(self):
        # Only meaningful while a client is connected — a closed
        # connection is handled instantly by on_disconnect(), not by
        # this timeout.
        if self.last_command_time is None or self.stopped_for_idle:
            return
        elapsed = time.monotonic() - self.last_command_time
        if elapsed > IDLE_TIMEOUT:
            self._stop_motor(f"idle {elapsed:.1f}s with connection still open")
            self.stopped_for_idle = True

    def poll_rpm(self):
        # Self-polls the bus directly — does not depend on a client
        # asking for `rpm`, so stall detection works even with nobody
        # connected at all (motor should never be spinning in that case
        # anyway, but this doesn't assume that).
        with self.lock:
            ret, value = linbus.get_rpm(self.lin)
        if ret == 0 and value is not None:
            self._check_stall(value)

    def monitor(self):
        # Runs in its own thread, independent of client connections.
        while True:
            time.sleep(RPM_POLL_INTERVAL)
            self.check_idle()
            self.poll_rpm()


def serve(address=SOCKET_ADDRESS, live=False):
    lin = linbus.Lin() if live else linbus.DryRunLin()
    print(f"watchdog: {'LIVE bus' if live else 'dry-run (no real bus access)'}")

    wd = Watchdog(lin)
    monitor_thread = threading.Thread(target=wd.monitor, daemon=True)
    monitor_thread.start()

    listener = Listener(address, family='AF_UNIX')
    print(f"watchdog listening on {address}")
    try:
        while True:
            with listener.accept() as conn:
                wd.on_connect()
                print("\nwatchdog: client connected")
                try:
                    while True:
                        try:
                            command = conn.recv()
                        except EOFError:
                            break
                        conn.send(wd.execute(command))
                finally:
                    wd.on_disconnect()
                    print("watchdog: client disconnected")
    except KeyboardInterrupt:
        print("\nwatchdog: shutting down (Ctrl+C)")
    finally:
        listener.close()
        lin.close()


if __name__ == "__main__":
    # Dry-run by default — real bus access requires the explicit --live
    # flag, so an accidental start can never move the motor. See
    # raspi/CLAUDE.md's Motor Execution Consent rule.
    serve(live='--live' in sys.argv[1:])
