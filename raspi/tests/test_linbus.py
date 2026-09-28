import threading

from linaddresses import constants
from linbus import (
    Lin, _log_pid_name, _log_source,
    ERR_UNKNOWN_PID, ERR_WRONG_LENGTH, ERR_WRONG_DIRECTION, ERR_ECHO_MISMATCH,
    ERR_TIMEOUT, ERR_BAD_CHECKSUM,
)

# Checksum/addparity (plus the --debug logging helpers below) are pure
# logic, no hardware needed. write()/read()/write_byte() below ARE now
# covered too (added 2026-09-28, Issue #12's Codex review -- the new
# distinct error constants weren't exercised by anything) via a fake
# serial object and _make_lin(), which bypasses Lin.__init__() entirely
# (that constructor hard-requires RPi.GPIO + a real port, see its own
# comment) rather than needing a real or dry-run connection.
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


# --- write()/read()/write_byte() error-branch coverage (added 2026-09-28,
# Issue #12's Codex review) -- fake serial, no hardware needed -------------

class _FakeSerial:
    """Minimal stand-in for pyserial's Serial -- only .write()/.read(1)
    are used by Lin. read_queue supplies what each successive .read(1)
    call returns (a single-byte `bytes` object for a real reply, `b""`
    to simulate a timeout/no response); once exhausted, further reads
    also return `b""`."""

    def __init__(self, read_queue=()):
        self.written = []  # one entry per .write() call, in order
        self._read_queue = list(read_queue)

    def write(self, data):
        self.written.append(data)

    def read(self, n=1):
        assert n == 1  # Lin never reads more than one byte at a time
        return self._read_queue.pop(0) if self._read_queue else b""


def _make_lin(read_queue=()):
    # Bypasses Lin.__init__() entirely -- that constructor hard-requires
    # RPi.GPIO + a real serial port (see its own comment), neither
    # available/wanted here. write()/read()/write_byte() only ever touch
    # self.ser, so this is enough to exercise them for real.
    lin = Lin.__new__(Lin)
    lin.ser = _FakeSerial(read_queue)
    return lin


WRITE_PID = constants.cntl3mot  # write-type (master->slave), 2-byte payload
READ_PID = constants.st2mot     # read-type (slave->master), 2-byte payload


def _echo_queue(*byte_values):
    # One matching-echo byte per write_byte() call, in order.
    return [bytes([b]) for b in byte_values]


# --- write() ----------------------------------------------------------

def test_write_unknown_pid():
    lin = _make_lin()
    assert lin.write(0xFF, [0x00, 0x00]) == ERR_UNKNOWN_PID
    assert lin.ser.written == []  # fails before touching the bus


def test_write_wrong_length():
    lin = _make_lin()
    assert lin.write(WRITE_PID, [0x00]) == ERR_WRONG_LENGTH  # needs 2 bytes
    assert lin.ser.written == []


def test_write_wrong_direction():
    # READ_PID is slave-sourced -- write() must refuse it.
    lin = _make_lin()
    assert lin.write(READ_PID, [0x00, 0x00]) == ERR_WRONG_DIRECTION
    assert lin.ser.written == []


def test_write_echo_mismatch_on_sync():
    lin = _make_lin(read_queue=[b"\x00"])  # wrong echo for constants.sync
    assert lin.write(WRITE_PID, [0x01, 0x02]) == ERR_ECHO_MISMATCH
    assert len(lin.ser.written) == 1  # stopped right after the bad byte


def test_write_echo_mismatch_on_data_byte():
    data = [0x01, 0x02]
    wire_pid = WRITE_PID  # instance defaults to 0x00
    good_header = _echo_queue(constants.sync, Lin.addparity(wire_pid))
    lin = _make_lin(read_queue=good_header + [b"\x00"])  # bad echo for data[0]
    assert lin.write(WRITE_PID, data) == ERR_ECHO_MISMATCH
    assert len(lin.ser.written) == 3  # sync, pid, the one bad data byte


def test_write_echo_mismatch_on_checksum():
    data = [0x01, 0x02]
    wire_pid = WRITE_PID
    good = _echo_queue(constants.sync, Lin.addparity(wire_pid), *data)
    lin = _make_lin(read_queue=good + [b"\x00"])  # bad echo for the checksum byte
    assert lin.write(WRITE_PID, data) == ERR_ECHO_MISMATCH
    assert len(lin.ser.written) == 5  # sync, pid, both data bytes, the bad checksum byte


def test_write_no_echo_at_all_is_a_mismatch():
    lin = _make_lin(read_queue=[])  # every .read(1) returns b""
    assert lin.write(WRITE_PID, [0x01, 0x02]) == ERR_ECHO_MISMATCH


def test_write_success():
    data = [0x01, 0x02]
    wire_pid = WRITE_PID
    checksum = Lin.checksum(data)
    good = _echo_queue(constants.sync, Lin.addparity(wire_pid), *data, checksum)
    lin = _make_lin(read_queue=good)
    assert lin.write(WRITE_PID, data) == 0
    assert lin.ser.written == [
        bytes([constants.sync]), bytes([Lin.addparity(wire_pid)]),
        bytes([0x01]), bytes([0x02]), bytes([checksum]),
    ]


# --- read() -------------------------------------------------------------

def test_read_unknown_pid():
    lin = _make_lin()
    ret, data = lin.read(0xFF)
    assert ret == ERR_UNKNOWN_PID
    assert data == []


def test_read_wrong_direction():
    # WRITE_PID is master-sourced -- read() must refuse it.
    lin = _make_lin()
    ret, data = lin.read(WRITE_PID)
    assert ret == ERR_WRONG_DIRECTION
    assert data == []


def test_read_echo_mismatch_on_header():
    lin = _make_lin(read_queue=[b"\x00"])  # wrong echo for constants.sync
    ret, data = lin.read(READ_PID)
    assert ret == ERR_ECHO_MISMATCH
    assert data == []


def test_read_timeout_on_first_data_byte_no_partial_data():
    wire_pid = READ_PID
    header = _echo_queue(constants.sync, Lin.addparity(wire_pid))
    lin = _make_lin(read_queue=header + [b""])  # nothing back for data[0]
    ret, data = lin.read(READ_PID)
    assert ret == ERR_TIMEOUT
    assert data == []


def test_read_timeout_on_second_data_byte_preserves_first():
    # READ_PID's payload is 2 bytes -- confirms the already-received
    # first byte survives into the returned (partial) data, per Codex's
    # review comment on this file.
    wire_pid = READ_PID
    header = _echo_queue(constants.sync, Lin.addparity(wire_pid))
    lin = _make_lin(read_queue=header + [bytes([0xAB]), b""])
    ret, data = lin.read(READ_PID)
    assert ret == ERR_TIMEOUT
    assert data == [0xAB]


def test_read_timeout_on_checksum_byte_preserves_full_data():
    wire_pid = READ_PID
    header = _echo_queue(constants.sync, Lin.addparity(wire_pid))
    lin = _make_lin(read_queue=header + [bytes([0xAB]), bytes([0xCD]), b""])
    ret, data = lin.read(READ_PID)
    assert ret == ERR_TIMEOUT
    assert data == [0xAB, 0xCD]


def test_read_bad_checksum_preserves_data():
    wire_pid = READ_PID
    payload = [0xAB, 0xCD]
    wrong_checksum = Lin.checksum(payload) ^ 0xFF
    header = _echo_queue(constants.sync, Lin.addparity(wire_pid))
    lin = _make_lin(read_queue=header + [bytes([0xAB]), bytes([0xCD]), bytes([wrong_checksum])])
    ret, data = lin.read(READ_PID)
    assert ret == ERR_BAD_CHECKSUM
    assert data == payload


def test_read_success():
    wire_pid = READ_PID
    payload = [0xAB, 0xCD]
    checksum = Lin.checksum(payload)
    header = _echo_queue(constants.sync, Lin.addparity(wire_pid))
    lin = _make_lin(read_queue=header + [bytes([0xAB]), bytes([0xCD]), bytes([checksum])])
    ret, data = lin.read(READ_PID)
    assert ret == 0
    assert data == payload


# --- write_byte() ---------------------------------------------------------

def test_write_byte_true_on_matching_echo():
    lin = _make_lin(read_queue=[bytes([0x42])])
    assert lin.write_byte(0x42) is True


def test_write_byte_false_on_mismatched_echo():
    lin = _make_lin(read_queue=[bytes([0x99])])
    assert lin.write_byte(0x42) is False


def test_write_byte_false_on_no_echo():
    lin = _make_lin(read_queue=[])
    assert lin.write_byte(0x42) is False


# --- write_bad_checksum() -------------------------------------------------

def test_write_bad_checksum_sends_a_wrong_checksum_byte():
    data = [0x01, 0x02]
    wire_pid = WRITE_PID
    correct_checksum = Lin.checksum(data)
    # Echo-check compares against whatever was actually written, so
    # queueing the (deliberately bad) checksum's own value as its echo
    # lets the call reach a clean return 0 -- the point of this test is
    # which byte got sent, not the echo-compare path (already covered
    # above via write()).
    lin = _make_lin()
    lin.ser._read_queue = _echo_queue(constants.sync, Lin.addparity(wire_pid), *data,
                                       correct_checksum ^ 0xFF)
    assert lin.write_bad_checksum(WRITE_PID, data) == 0
    sent_checksum_byte = lin.ser.written[-1]
    assert sent_checksum_byte == bytes([correct_checksum ^ 0xFF])
    assert sent_checksum_byte != bytes([correct_checksum])


def test_write_bad_checksum_shares_writes_early_return_branches():
    lin = _make_lin()
    assert lin.write_bad_checksum(0xFF, [0x00, 0x00]) == ERR_UNKNOWN_PID
    assert lin.write_bad_checksum(WRITE_PID, [0x00]) == ERR_WRONG_LENGTH
    assert lin.write_bad_checksum(READ_PID, [0x00, 0x00]) == ERR_WRONG_DIRECTION
