"""Step-response capture: speed 0 -> speed <target>, sampling `rpm` at a
fixed interval for a fixed duration, plus `current` at a slower interval.
Real hardware, not a pytest test case — see raspi/CLAUDE.md's Test Suite
Policy. Falls under Motor Execution Consent like any other motor
command, whether run manually on the Pi or triggered remotely.

Prints CSV (elapsed_ms,rpm,current_val1,current_val2) to stdout, one row
per rpm sample. current_val1/val2 are only filled in once every
CURRENT_SAMPLE_INTERVAL (default 1.0s) -- the current sensor's own
on-board averaging window is ~1s (see currentsensor/CLAUDE.md's
countmax/OCR1A tuning), so sampling it faster than that would just
re-read the same averaged value repeatedly. Does not write a CSV file
itself — the caller decides where the data ends up (e.g. saved into
runs/ in the main repo).

Separately, every command sent and reply received is also logged (with
timestamps) to capture_step_response.log (rotated, one generation kept,
see logsetup.rotate_log()) — file only, not echoed to the terminal,
since stdout is reserved for the CSV stream above. See
raspi/watchdog/CLAUDE.md's log-format notes.

Optional --p-delta/--i-delta (added 2026-08-19): if given, sends
`pi <p_delta> <i_delta>` as the very first command, before `speed 0` —
so an out-of-range value (rejected by the watchdog's own validate(),
see watchdog.py's PI_DELTA_MIN/MAX) aborts before the motor moves at
all, not partway through. Range is intentionally NOT re-checked here —
the watchdog is the single source of truth for that, see
run_experiment.py's own docstring for why duplicating it client-side
was deliberately avoided. Omit both to leave KP/KI at their firmware
defaults, same as never calling `pi` at all.

Ends with a staged soft stop (added 2026-08-20), not a single abrupt
`speed 0` — see _soft_stop()'s own docstring for why. Runs after the
sampling loop closes, so it has no effect on the printed CSV/any
ISE-style scoring computed from it.
"""
import argparse
import logging
import re
import sys
import time
from multiprocessing.connection import Client

import logsetup
from motorcontrol import SOCKET_ADDRESS

LOG_PATH = "capture_step_response.log"
logger = logging.getLogger("capture_step_response")

TARGET_SPEED = 1000
SAMPLE_INTERVAL = 0.2  # seconds, rpm sampling
CURRENT_SAMPLE_INTERVAL = 1.0  # seconds -- matches the current sensor's own averaging window
DURATION = 7.0  # seconds, measured from the speed step, not from speed 0

STOP_RAMP_STEPS = 5  # number of speed commands sent during the soft stop, last one is always 0
STOP_RAMP_DURATION = 1.0  # seconds, total time from the first reduced speed to the final 0

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


def _soft_stop(conn, target_speed, steps=STOP_RAMP_STEPS, duration=STOP_RAMP_DURATION):
    # A single abrupt `speed 0` after a sustained high speed was
    # observed live (2026-08-20) to stop the motor harder than a plain
    # coast-down would -- plausibly the PI controller reacting to a
    # sudden large negative error rather than the rotor just freewheeling
    # down under friction. Firmware's own updateramp() stays disabled
    # (updateramp(false), see STM32/CLAUDE.md's Commutation & Control
    # section) deliberately -- re-enabling it would also smooth the
    # *start* of the step, undoing the whole point of turning it off.
    # This ramps down in stages from the Python side instead, only
    # affecting the stop.
    step_interval = duration / (steps - 1)
    for i in range(steps - 1, 0, -1):
        _send(conn, f"speed {round(target_speed * i / steps)}")
        time.sleep(step_interval)
    _send(conn, "speed 0")


def run(address=SOCKET_ADDRESS, target_speed=TARGET_SPEED,
        sample_interval=SAMPLE_INTERVAL,
        current_sample_interval=CURRENT_SAMPLE_INTERVAL, duration=DURATION,
        p_delta=None, i_delta=None):
    logsetup.configure("capture_step_response", LOG_PATH, terminal_level=None)

    # One persistent connection for the whole run — see
    # validate_speed.py's same choice for why (one-shot connections
    # trigger the watchdog's stop-on-disconnect after every command).
    with Client(address, family='AF_UNIX') as conn:
        if p_delta is not None or i_delta is not None:
            reply = _send(conn, f"pi {p_delta} {i_delta}")
            if not reply.startswith("OK"):
                sys.exit(f"pi command rejected, aborting before touching the motor: {reply}")
        _send(conn, "speed 0")
        _send(conn, f"speed {target_speed}")
        start = time.monotonic()
        next_current_sample = start

        print("elapsed_ms,rpm,current_val1,current_val2")
        sample_count = int(duration / sample_interval)
        for i in range(sample_count):
            # Scheduled against the absolute start time, not
            # accumulated sleeps, so LIN round-trip latency for each
            # rpm read doesn't drift the sample interval over the run.
            target_time = start + i * sample_interval
            now = time.monotonic()
            if target_time > now:
                time.sleep(target_time - now)
            rpm = _read_rpm(conn)

            current_val1 = current_val2 = ""
            if time.monotonic() >= next_current_sample:
                current_val1, current_val2 = _read_current(conn)
                next_current_sample += current_sample_interval

            elapsed_ms = (time.monotonic() - start) * 1000
            print(f"{elapsed_ms:.0f},{rpm},{current_val1},{current_val2}")

        _soft_stop(conn, target_speed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--p-delta", type=float, default=None)
    parser.add_argument("--i-delta", type=float, default=None)
    args = parser.parse_args()
    if (args.p_delta is None) != (args.i_delta is None):
        sys.exit("--p-delta and --i-delta must be given together, or not at all")
    run(p_delta=args.p_delta, i_delta=args.i_delta)
