"""Step-response capture: speed 0 -> speed <target>, sampling `rpm` at a
fixed interval for a fixed duration. Real hardware, not a pytest test
case — see raspi/CLAUDE.md's Test Suite Policy. Falls under Motor
Execution Consent like any other motor command, whether run manually on
the Pi or triggered remotely.

Prints CSV (elapsed_ms,rpm) to stdout, one row per sample. Does not
write a file itself — the caller decides where the data ends up (e.g.
saved into runs/ in the main repo).
"""
import re
import time
from multiprocessing.connection import Client

from motorcontrol import SOCKET_ADDRESS

TARGET_SPEED = 1000
SAMPLE_INTERVAL = 0.2  # seconds
DURATION = 8.0  # seconds, measured from the speed step, not from speed 0

RPM_RE = re.compile(r"rpm=(-?\d+)")


def _read_rpm(conn):
    conn.send("rpm")
    match = RPM_RE.search(conn.recv())
    return int(match.group(1)) if match else None


def run(address=SOCKET_ADDRESS, target_speed=TARGET_SPEED,
        sample_interval=SAMPLE_INTERVAL, duration=DURATION):
    # One persistent connection for the whole run — see
    # validate_speed.py's same choice for why (one-shot connections
    # trigger the watchdog's stop-on-disconnect after every command).
    with Client(address, family='AF_UNIX') as conn:
        conn.send("speed 0")
        conn.recv()

        conn.send(f"speed {target_speed}")
        conn.recv()
        start = time.monotonic()

        print("elapsed_ms,rpm")
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
            elapsed_ms = (time.monotonic() - start) * 1000
            print(f"{elapsed_ms:.0f},{rpm}")

        conn.send("speed 0")
        conn.recv()


if __name__ == "__main__":
    run()
