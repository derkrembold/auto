import logging
from multiprocessing.connection import Client

import logsetup

try:
    # Side-effect import: hooks GNU readline into input(), giving
    # arrow-key command history/line-editing for free. Unix/Pi only —
    # not in the stdlib on Windows, so this must not be fatal when
    # testing locally there.
    import readline  # noqa: F401
except ImportError:
    pass

# This talks to the watchdog over local IPC, it does not touch LIN
# directly — the watchdog is the sole LIN master. See
# raspi/watchdog/CLAUDE.md's "Architecture: Sole LIN Master" section.
# Must match watchdog.py's SOCKET_ADDRESS.
SOCKET_ADDRESS = '/tmp/motorwatchdog.sock'

# Rotated (one generation kept, see logsetup.rotate_log()) on every
# main() start. Always mirrored to the terminal too -- unlike
# watchdog.py, there's no high-frequency self-polling noise here, every
# line corresponds to an explicit command a human typed. See
# raspi/watchdog/CLAUDE.md's log-format notes.
LOG_PATH = "motorcontrol.log"

logger = logging.getLogger("motorcontrol")

HELP_TEXT = """Commands:
  speed <value>   set speed, 0 = stop
  on              status LED on
  off             status LED off
  hal             read Hall sensor positions
  rpm             read RPM over LIN
  temp            read temperature
  current         read current sensor (amps, val1/val2 = ACS712 #1/#2)
  errors          read currentsensor's last 8 error codes (most recent first)
  selftest        currentsensor errorstorage roundtrip + deliberately provoke a
                  currentsensor/STM32 bus-hang timeout + deliberately send a
                  bad-checksum speed-0 write and confirm all were caught
                  (real hardware, ~2s, deliberately disrupts the bus for a moment)
  help            show this again
  exit            quit (Ctrl+C also works)
"""


def send_command(command, address=SOCKET_ADDRESS):
    # One-shot helper — opens its own connection, sends one command,
    # closes. Useful for scripts that want to import this directly
    # (e.g. a future optimization loop). main() below does NOT use this
    # — it holds one persistent connection for the whole session instead
    # (see watchdog.py's on_connect()/on_disconnect(), which rely on
    # that connection staying open for the "is the supervisor alive"
    # check).
    with Client(address, family='AF_UNIX') as conn:
        conn.send(command)
        return conn.recv()


def main():
    logsetup.configure("motorcontrol", LOG_PATH, terminal_level=logging.INFO)
    with Client(SOCKET_ADDRESS, family='AF_UNIX') as conn:
        logger.info("connected to watchdog")
        print(HELP_TEXT)
        while True:
            try:
                command = input("motorcontrol> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not command:
                continue
            if command in ("exit", "quit"):
                break
            if command == "help":
                print(HELP_TEXT)
                continue
            logger.info(f"-> {command}")
            conn.send(command)
            reply = conn.recv()
            logger.info(f"<- {reply}")


if __name__ == "__main__":
    main()
