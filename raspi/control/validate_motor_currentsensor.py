"""Motor + currentsensor bus-coexistence validation — real hardware, not
a pytest test case. Regression check for the LIN receive-state-machine
hang found 2026-08-07: STM32's HAL_UART_RxCpltCallback didn't re-arm UART
reception for a recognized-but-foreign pid (e.g. st0cur, when `current`
is queried while the motor is running) — see STM32/CLAUDE.md and
currentsensor/CLAUDE.md for the fix on both sides of the bus. Exercises
exactly that scenario: motor speed steps interleaved with `current`/
`hal`/`rpm` queries.

Run on the Pi with the watchdog already running (--live). Falls under
raspi/CLAUDE.md's Motor Execution Consent rule like any other motor
command, whether started manually on the Pi or triggered remotely.
"""
import re
import time
from multiprocessing.connection import Client

from motorcontrol import SOCKET_ADDRESS

SPEED_SEQUENCE = [0, 500, 1000, 500, 0]
CHECKS = ["current", "hal", "rpm"]

# Time to let the motor settle after a speed change before querying it.
SETTLE_TIME = 3.0

# linbus.get_current() converts the sensor's raw 10-bit ADC reading to
# amps (see linbus.py's _adc_to_amps()/ACS712_* constants) -- the full
# 0-1023 ADC span maps to roughly -25 A..+25 A, so a val1/val2 outside
# that means something is wrong at the protocol/parsing level (corrupted
# reply, wrong byte count, ...), not a plausible current reading. Not a
# "near 0 A" check (that would need a confirmed noise tolerance, not
# available yet) -- just a basic sanity bound.
CURRENT_AMPS_MIN = -25.0
CURRENT_AMPS_MAX = 25.0

CURRENT_REPLY_RE = re.compile(r"OK ret=(-?\d+) val1=(\S+) val2=(\S+)")


def _invalid_current_reason(reply):
    # Returns None if the reply looks plausible, otherwise a description
    # of what's wrong with it.
    match = CURRENT_REPLY_RE.match(reply)
    if not match:
        return f"unparseable reply: {reply!r}"
    ret_str, val1_str, val2_str = match.groups()
    if int(ret_str) != 0:
        return f"current read failed (ret={ret_str}): {reply!r}"
    try:
        val1, val2 = float(val1_str), float(val2_str)
    except ValueError:
        return f"non-numeric current value(s): {reply!r}"
    if not (CURRENT_AMPS_MIN <= val1 <= CURRENT_AMPS_MAX
            and CURRENT_AMPS_MIN <= val2 <= CURRENT_AMPS_MAX):
        return (f"current value outside plausible "
                f"{CURRENT_AMPS_MIN}..{CURRENT_AMPS_MAX} A range: {reply!r}")
    return None


def run(address=SOCKET_ADDRESS, speed_sequence=SPEED_SEQUENCE, checks=CHECKS,
        settle_time=SETTLE_TIME):
    # One persistent connection for the whole run, not one-shot
    # send_command() per step — see validate_speed.py's comment for why
    # (a one-shot connection's immediate disconnect would trigger the
    # watchdog's on_disconnect() stop after every single step).
    with Client(address, family='AF_UNIX') as conn:
        for value in speed_sequence:
            conn.send(f"speed {value}")
            print(f"speed {value} -> {conn.recv()}")

            time.sleep(settle_time)

            for check in checks:
                conn.send(check)
                reply = conn.recv()
                print(f"{check:8s}   -> {reply}")

                if check == "current":
                    reason = _invalid_current_reason(reply)
                    if reason:
                        print(f"ABORT: implausible current reading — {reason}")
                        conn.send("speed 0")
                        print(f"speed 0  -> {conn.recv()}")
                        return


if __name__ == "__main__":
    run()
