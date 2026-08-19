import threading

from linaddresses import constants
from linbus import Lin, _log_pid_name, _log_source

# Only checksum/addparity (plus the --debug logging helpers below) are
# tested here — they're the pure-logic parts of linbus.py (no hardware
# needed). Everything else on Lin (write, read, write_byte) needs a real
# or dry-run serial connection — not covered here yet, see
# raspi/watchdog/CLAUDE.md's Test Suite section.
#
# Expected values below were computed once from the algorithm itself and
# frozen as regression references — this is a change-detector for the
# exact tested-on-hardware behavior, not an independent verification
# that the LIN parity/checksum math is "correct" in the abstract.


def test_checksum_payload_a():
    # Frozen regression value -- not tied to any current command's
    # meaning (these bytes were the removed on/off LED payload), just
    # exercising checksum() over a fixed byte pair.
    assert Lin.checksum([0x01, 0xdb]) == 0x23


def test_checksum_payload_b():
    assert Lin.checksum([0xcd, 0x0c]) == 0x26


def test_checksum_all_zero():
    assert Lin.checksum([0x00, 0x00]) == 0xff


def test_checksum_all_ff():
    assert Lin.checksum([0xff, 0xff]) == 0x00


def test_addparity_known_pids():
    # Frozen regression values from the old (pre-instance-addressing)
    # scheme -- addparity() is pure pid-bit math, unaffected by the
    # cntlslv*/cntl*mot renaming, so these stay valid as-is.
    assert Lin.addparity(0x09) == 0x49
    assert Lin.addparity(0x39) == 0x39
    assert Lin.addparity(0x04) == 0xc4
    assert Lin.addparity(0x1b) == 0x5b
    assert Lin.addparity(0x2e) == 0x2e
    assert Lin.addparity(0x55) == 0x55  # sync


# --- --debug logging helpers (raspi/watchdog/CLAUDE.md's log-format
# redesign, 2026-08-12) -- pure logic, no hardware needed.

def test_log_pid_name_known_pid():
    assert _log_pid_name(constants.cntl3mot) == "cntl3mot"
    assert _log_pid_name(constants.st0cur) == "st0cur"


def test_log_pid_name_unknown_pid_falls_back_to_hex():
    assert _log_pid_name(0xFF) == "0xff"


def test_log_source_main_thread_is_client():
    # Watchdog.execute() (client commands) always runs on the main
    # thread -- see serve()'s accept loop, which isn't spawned as its
    # own thread.
    assert _log_source() == "[client]"


def test_log_source_background_thread_is_poll():
    # Watchdog.monitor() (self-polling) runs in its own daemon thread.
    result = {}

    def capture():
        result["source"] = _log_source()

    t = threading.Thread(target=capture)
    t.start()
    t.join()

    assert result["source"] == "[poll]  "
