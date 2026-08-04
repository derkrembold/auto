"""Speed-ramp validation sequence — real hardware, not a pytest test
case. See root CLAUDE.md's Open Points ("does `speed` really mean
RPM?") and raspi/CLAUDE.md's Test Suite Policy for why this lives here
as a standalone script, not in raspi/tests/.

Run on the Pi with the watchdog already running (--live). Falls under
raspi/CLAUDE.md's Motor Execution Consent rule like any other motor
command, whether started manually on the Pi or triggered remotely.
"""
import time
from multiprocessing.connection import Client

from motorcontrol import SOCKET_ADDRESS

SEQUENCE = [0, 400, 800, 1200, 800, 400, 0, -400, -800, -1200, -800, -400, 0]

# Time to let rpm settle after a speed change before reading it back.
SETTLE_TIME = 3.0


def run(address=SOCKET_ADDRESS, sequence=SEQUENCE, settle_time=SETTLE_TIME):
    # One persistent connection for the whole run, not one-shot
    # send_command() per step — a one-shot connection's immediate
    # disconnect would trigger the watchdog's on_disconnect() stop after
    # every single step (see watchdog/CLAUDE.md's Connection Model),
    # which would undo the ramp this is trying to validate.
    with Client(address, family='AF_UNIX') as conn:
        for value in sequence:
            conn.send(f"speed {value}")
            print(f"speed {value} -> {conn.recv()}")

            time.sleep(settle_time)

            conn.send("rpm")
            print(f"rpm check   -> {conn.recv()}")


if __name__ == "__main__":
    run()
