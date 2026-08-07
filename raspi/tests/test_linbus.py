from linbus import Lin

# Only checksum/addparity are tested here — they're the pure-math parts
# of Lin (@staticmethod, no self, no hardware). Everything else on Lin
# (write, read, write_byte) needs a real or dry-run serial connection —
# not covered here yet, see raspi/watchdog/CLAUDE.md's Test Suite
# section.
#
# Expected values below were computed once from the algorithm itself and
# frozen as regression references — this is a change-detector for the
# exact tested-on-hardware behavior, not an independent verification
# that the LIN parity/checksum math is "correct" in the abstract.


def test_checksum_led_on_payload():
    assert Lin.checksum([0x01, 0xdb]) == 0x23


def test_checksum_led_off_payload():
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
