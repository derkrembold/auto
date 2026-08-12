"""Speed-ramp validation sequence — real hardware, not a pytest test
case. See root CLAUDE.md's Open Points ("does `speed` really mean
RPM?") and raspi/CLAUDE.md's Test Suite Policy for why this lives here
as a standalone script, not in raspi/tests/.

Prints CSV (elapsed_ms,speed,rpm,current_val1,current_val2) to stdout,
one row per step in the sequence — same column shape as
capture_step_response.py's output (plus a `speed` column, since this is
a multi-step ramp rather than one fixed target), so /plot-step-response
can plot this too. Does not write a CSV file itself.

Separately, every command sent and reply received is also logged (with
timestamps) to validate_speed.log (rotated, one generation kept, see
logsetup.rotate_log()) — file only, not echoed to the terminal, since
stdout is reserved for the CSV stream above (e.g. when redirected into
a file). See raspi/watchdog/CLAUDE.md's log-format notes.

Run on the Pi with the watchdog already running (--live). Falls under
raspi/CLAUDE.md's Motor Execution Consent rule like any other motor
command, whether started manually on the Pi or triggered remotely.
"""
import logging
import re
import time
from multiprocessing.connection import Client

import logsetup
from motorcontrol import SOCKET_ADDRESS

LOG_PATH = "validate_speed.log"
logger = logging.getLogger("validate_speed")

SEQUENCE = [0, 400, 800, 1200, 800, 400, 0, -400, -800, -1200, -800, -400, 0]

# Time to let rpm/current settle after a speed change before reading them
# back. Deliberately longer than the current sensor's own ~1s on-board
# averaging window (see currentsensor/CLAUDE.md's countmax/OCR1A
# tuning) — unlike capture_step_response.py, current doesn't need its
# own slower sampling schedule here; every step's settle time already
# covers it, so it's read once per step right alongside rpm.
SETTLE_TIME = 3.0

RPM_RE = re.compile(r"rpm=(-?\d+)")
CURRENT_RE = re.compile(r"val1=(\S+) val2=(\S+)")


def _send(conn, command):
    logger.info(f"-> {command}")
    conn.send(command)
    reply = conn.recv()
    logger.info(f"<- {reply}")
    return reply


def _read_rpm(conn):
    match = RPM_RE.search(_send(conn, "rpm"))
    return int(match.group(1)) if match else None


def _read_current(conn):
    match = CURRENT_RE.search(_send(conn, "current"))
    return (match.group(1), match.group(2)) if match else (None, None)


def run(address=SOCKET_ADDRESS, sequence=SEQUENCE, settle_time=SETTLE_TIME):
    logsetup.configure("validate_speed", LOG_PATH, terminal_level=None)

    # One persistent connection for the whole run, not one-shot
    # send_command() per step — a one-shot connection's immediate
    # disconnect would trigger the watchdog's on_disconnect() stop after
    # every single step (see watchdog/CLAUDE.md's Connection Model),
    # which would undo the ramp this is trying to validate.
    with Client(address, family='AF_UNIX') as conn:
        start = time.monotonic()
        print("elapsed_ms,speed,rpm,current_val1,current_val2")
        for value in sequence:
            _send(conn, f"speed {value}")

            time.sleep(settle_time)

            rpm = _read_rpm(conn)
            current_val1, current_val2 = _read_current(conn)
            elapsed_ms = (time.monotonic() - start) * 1000
            print(f"{elapsed_ms:.0f},{value},{rpm},{current_val1},{current_val2}")


if __name__ == "__main__":
    run()
