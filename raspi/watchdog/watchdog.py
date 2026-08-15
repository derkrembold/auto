import logging
import sys
import threading
import time
from multiprocessing.connection import Listener

import linbus
import logsetup

# Must match motorcontrol.py's SOCKET_ADDRESS.
SOCKET_ADDRESS = '/tmp/motorwatchdog.sock'

# Rotated (one generation kept, see logsetup.rotate_log()) on every
# serve() start -- always full detail, independent of --debug (which
# only controls terminal echo). See raspi/watchdog/CLAUDE.md's
# log-format notes.
LOG_PATH = "watchdog.log"

logger = logging.getLogger("watchdog")

KNOWN_COMMANDS = {"speed", "on", "off", "hal", "rpm", "temp", "current", "errors", "selftest"}

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

# Upper-layer stall signature (see "Two-Layer Safety Check" below):
# "no current" baseline for linbus.get_current()'s val1 (amps). Needs
# real headroom above ACS712 chip-to-chip offset tolerance -- observed
# ~0.05-0.09A between the two sensor chips on real hardware, see
# currentsensor/CLAUDE.md's Hardware section. Kept as its own named
# constant (not inlined) so it's easy to find and retune once more
# real-world data exists.
CURRENT_STALL_THRESHOLD = 0.15

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

        # Lower layer: rpm-only stall check (self-stopping, live).
        self.last_commanded_speed = 0
        self.speed_became_nonzero_at = None

        # Upper layer: current-based stall *signature* — observe-only
        # for now (logs, does not stop the motor yet). See "Two-Layer
        # Safety Check" in raspi/watchdog/CLAUDE.md for why: the sensor
        # only just started working reliably (2026-08-10/11), not yet
        # trusted enough to act on autonomously.
        self.last_known_rpm = None

    def _advance_spinner(self):
        char = SPINNER_CHARS[self.spinner_index % len(SPINNER_CHARS)]
        self.spinner_index += 1
        print(f"\rwatchdog: {char}  ", end="", flush=True)

    def _stop_motor(self, reason):
        logger.warning(f"{reason} — stopping motor")
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
        if verb == "current":
            ret, val1, val2 = linbus.get_current(self.lin)
            val1_str = f"{val1:.2f}" if val1 is not None else None
            val2_str = f"{val2:.2f}" if val2 is not None else None
            return f"OK ret={ret} val1={val1_str} val2={val2_str}"
        if verb == "errors":
            # Currentsensor's own errorstorage ring buffer -- the motor
            # side has no equivalent (its st3mot is a single running
            # counter, not a per-error-type history, see "selftest"
            # below).
            ret, codes = linbus.get_error_history(self.lin)
            names = ([linbus.CURRENTSENSOR_ERROR_NAMES.get(c, str(c)) for c in codes]
                      if codes is not None else None)
            return f"OK ret={ret} codes={codes} names={names}"
        if verb == "selftest":
            # Part 1: currentsensor's cntl0cur test hook, round-trip
            # inject-then-reset of errorstorage via st1cur.
            (ret_inject, ret_injected, codes_injected,
             ret_reset, ret_after_reset, codes_after_reset) = linbus.currentsensor_selftest(self.lin)
            names_injected = ([linbus.CURRENTSENSOR_ERROR_NAMES.get(c, str(c)) for c in codes_injected]
                                if codes_injected is not None else None)
            names_after_reset = ([linbus.CURRENTSENSOR_ERROR_NAMES.get(c, str(c)) for c in codes_after_reset]
                                   if codes_after_reset is not None else None)

            # Part 1.5: deliberately provoke currentsensor's cntl0cur
            # checksum gate (see linbus.provoke_currentsensor_checksum_
            # error()'s docstring) and confirm both that the error was
            # logged AND that the inject action was actually skipped --
            # errorstorage should show a fresh CHK entry but NOT the
            # inject pattern's 0x11 byte. Also confirms via the STM32's
            # own counters that it correctly attributes this to nobody
            # (message wasn't addressed to it), even though it still
            # sees the frame go by on the shared bus.
            ret_motor_counters_before0, timeout_before0, checksum_before0 = linbus.get_motor_counters(self.lin)
            ret_bad_cs_write = linbus.provoke_currentsensor_checksum_error(self.lin)
            ret_errors_after0, codes_after_cs_provoke = linbus.get_error_history(self.lin)
            names_after_cs_provoke = ([linbus.CURRENTSENSOR_ERROR_NAMES.get(c, str(c)) for c in codes_after_cs_provoke]
                                        if codes_after_cs_provoke is not None else None)
            ret_motor_counters_after0, timeout_after0, checksum_after0 = linbus.get_motor_counters(self.lin)

            # Part 2: deliberately provoke the STM32 bus-hang timeout
            # (see linbus.provoke_bus_hang_timeout()'s docstring) and
            # confirm both sides actually caught it -- STM32's
            # bodyTimeoutCount (st3mot) went up, currentsensor logged a
            # CHK error (st1cur). Takes ~2s (the master's own read
            # timeout on the deliberately-sabotaged reply).
            ret_counters_before, timeout_before, checksum_before = linbus.get_motor_counters(self.lin)
            ret_arm, ret_trigger = linbus.provoke_bus_hang_timeout(self.lin)
            ret_counters_after, timeout_after, checksum_after = linbus.get_motor_counters(self.lin)
            ret_errors_after, codes_after_provoke = linbus.get_error_history(self.lin)
            names_after_provoke = ([linbus.CURRENTSENSOR_ERROR_NAMES.get(c, str(c)) for c in codes_after_provoke]
                                     if codes_after_provoke is not None else None)

            # Part 3: deliberately provoke the STM32's checksum_ok gate
            # (see linbus.provoke_checksum_error()'s docstring) and
            # confirm checksumErrorCount went up by exactly 1. Safe
            # without Motor Execution Consent -- the corrupted write is a
            # "speed 0", harmless even if the gate were somehow broken.
            # Only proves detection, not that the motor's setpoint truly
            # didn't change -- see that function's docstring for the
            # (not yet built) direct rpm-based proof.
            ret_counters_before2, timeout_before2, checksum_before2 = linbus.get_motor_counters(self.lin)
            ret_bad_write = linbus.provoke_checksum_error(self.lin)
            ret_counters_after2, timeout_after2, checksum_after2 = linbus.get_motor_counters(self.lin)

            return (f"OK inject_ret={ret_inject} "
                    f"injected(ret={ret_injected} codes={codes_injected} names={names_injected}) "
                    f"reset_ret={ret_reset} "
                    f"after_reset(ret={ret_after_reset} codes={codes_after_reset} names={names_after_reset}) "
                    f"currentsensor_checksum_test("
                    f"motor_before(ret={ret_motor_counters_before0} timeout={timeout_before0} checksum={checksum_before0}) "
                    f"bad_write_ret={ret_bad_cs_write} "
                    f"currentsensor_after(ret={ret_errors_after0} codes={codes_after_cs_provoke} names={names_after_cs_provoke}) "
                    f"motor_after(ret={ret_motor_counters_after0} timeout={timeout_after0} checksum={checksum_after0})) "
                    f"bushang_test(before(ret={ret_counters_before} timeout={timeout_before} checksum={checksum_before}) "
                    f"arm_ret={ret_arm} trigger_ret={ret_trigger} "
                    f"after(ret={ret_counters_after} timeout={timeout_after} checksum={checksum_after}) "
                    f"currentsensor_after(ret={ret_errors_after} codes={codes_after_provoke} "
                    f"names={names_after_provoke})) "
                    f"checksum_test(before(ret={ret_counters_before2} timeout={timeout_before2} checksum={checksum_before2}) "
                    f"bad_write_ret={ret_bad_write} "
                    f"after(ret={ret_counters_after2} timeout={timeout_after2} checksum={checksum_after2}))")
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
        # anyway, but this doesn't assume that). Per-call tracing (which
        # thread, timing, raw bytes) now lives in linbus.Lin itself (see
        # its --debug support) rather than being duplicated here.
        with self.lock:
            ret, value = linbus.get_rpm(self.lin)
        if ret == 0 and value is not None:
            self.last_known_rpm = value
            self._check_stall(value)

    def poll_current(self):
        # Upper-layer stall *signature* check (see "Two-Layer Safety
        # Check" in raspi/watchdog/CLAUDE.md): current flowing while rpm
        # reads 0. Observe-only — logs conspicuously, does NOT call
        # _stop_motor() yet. Only val1 (val2 is reserved for a second
        # motor once one exists on the bus, not a redundant reading of
        # this one — see currentsensor/CLAUDE.md's Hardware section).
        # Uses the rpm value poll_rpm() already cached this same tick
        # rather than issuing a second rpm read.
        with self.lock:
            ret, val1, val2 = linbus.get_current(self.lin)
        if ret != 0 or val1 is None:
            return
        if self.last_known_rpm == 0 and abs(val1) > CURRENT_STALL_THRESHOLD:
            logger.warning(f"*** OBSERVED STALL SIGNATURE (not acted on "
                            f"yet) — current={val1:.2f}A while rpm=0 ***")

    def monitor(self):
        # Runs in its own thread, independent of client connections. Must
        # never die from a single bad poll (e.g. a bus timeout) — that
        # would silently disable self-polled stall detection for the rest
        # of the process's life, with nothing but a printed traceback to
        # notice by.
        while True:
            time.sleep(RPM_POLL_INTERVAL)
            try:
                self.check_idle()
                self.poll_rpm()
                self.poll_current()
            except Exception as exc:
                logger.error(f"monitor loop error (continuing): {exc}")


def serve(address=SOCKET_ADDRESS, live=False, debug=False):
    # File always gets full detail (DEBUG level); terminal only mirrors
    # it if --debug. Log file is rotated (one generation kept) here, not
    # overwritten -- a rare bug's evidence must survive an untimely
    # restart. See raspi/watchdog/CLAUDE.md's log-format notes.
    logsetup.configure(
        "watchdog", LOG_PATH,
        terminal_level=logging.DEBUG if debug else logging.INFO,
    )

    # One-time session header -- which process, live vs dry-run, whether
    # --debug is on. Session-level facts belong here, not repeated on
    # every subsequent log line.
    mode = "LIVE bus" if live else "dry-run (no real bus access)"
    debug_note = " [debug]" if debug else ""
    logger.info(f"=== watchdog.py — {mode}{debug_note} ===")

    lin = linbus.Lin() if live else linbus.DryRunLin()

    wd = Watchdog(lin)
    monitor_thread = threading.Thread(target=wd.monitor, daemon=True)
    monitor_thread.start()

    listener = Listener(address, family='AF_UNIX')
    logger.info(f"listening on {address}")
    try:
        while True:
            with listener.accept() as conn:
                wd.on_connect()
                logger.info("client connected")
                try:
                    while True:
                        try:
                            command = conn.recv()
                        except EOFError:
                            break
                        conn.send(wd.execute(command))
                finally:
                    wd.on_disconnect()
                    logger.info("client disconnected")
    except KeyboardInterrupt:
        logger.info("shutting down (Ctrl+C)")
    finally:
        listener.close()
        lin.close()


if __name__ == "__main__":
    # Dry-run by default — real bus access requires the explicit --live
    # flag, so an accidental start can never move the motor. See
    # raspi/CLAUDE.md's Motor Execution Consent rule.
    # --debug: also echo the full LIN bus-call trace (linbus.Lin,
    # timestamped, ->/<- entry+exit, which thread) to the terminal, not
    # just watchdog.log (which always has it regardless of this flag).
    # See raspi/watchdog/CLAUDE.md's log-format notes.
    serve(live='--live' in sys.argv[1:], debug='--debug' in sys.argv[1:])
