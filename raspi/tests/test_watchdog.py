import pytest

from watchdog import validate, Watchdog, SPEED_MIN, SPEED_MAX, IDLE_TIMEOUT
from linbus import DryRunLin, MOTOR_INSTANCE_ID
from linaddresses import constants

# Unit tests only — pure logic, no sockets, no hardware. Runs anywhere,
# including natively on Windows. Integration tests (real Listener/Client
# over AF_UNIX) need Linux — see raspi/watchdog/CLAUDE.md's Test Suite
# section for why.

RANGE_ERROR = f"speed value out of range ({SPEED_MIN}..{SPEED_MAX})"

# Expected on-wire pid for motor commands: base pid combined with the one
# motor currently on the bus's strap-pin instance id — see linbus.py's
# TARGET_MOTOR_INSTANCE comment.
CNTL0MOT_WIRE = constants.cntl0mot | MOTOR_INSTANCE_ID
CNTL3MOT_WIRE = constants.cntl3mot | MOTOR_INSTANCE_ID


@pytest.mark.parametrize("command,expected", [
    ("speed 300", (True, None)),
    ("speed -300", (True, None)),
    ("speed 0", (True, None)),
    (f"speed {SPEED_MAX}", (True, None)),
    (f"speed {SPEED_MIN}", (True, None)),
    (f"speed {SPEED_MAX + 1}", (False, RANGE_ERROR)),
    (f"speed {SPEED_MIN - 1}", (False, RANGE_ERROR)),
    ("speed abc", (False, "speed value must be an integer")),
    ("speed", (False, "usage: speed <value>")),
    ("speed 1 2", (False, "usage: speed <value>")),
    ("on", (True, None)),
    ("off", (True, None)),
    ("hal", (True, None)),
    ("rpm", (True, None)),
    ("temp", (True, None)),
    ("current", (True, None)),
    ("on extra", (False, "usage: on")),
    ("banana", (False, "unknown command: banana")),
    ("", (False, "empty command")),
])
def test_validate(command, expected):
    assert validate(command) == expected


def test_execute_invalid_command_returns_err_with_reason():
    wd = Watchdog(DryRunLin())
    assert wd.execute("banana") == "ERR unknown command: banana"
    assert wd.lin.writes == []  # never reaches the bus


def test_execute_speed_relays_to_dry_run_bus():
    wd = Watchdog(DryRunLin())
    assert wd.execute("speed 300") == "OK"
    assert len(wd.lin.writes) == 1
    address, data = wd.lin.writes[0]
    assert address == CNTL3MOT_WIRE
    assert data == [0x01, 0x2c]  # struct.pack('>h', 300)


def test_execute_on_off_relay_to_dry_run_bus():
    wd = Watchdog(DryRunLin())
    wd.execute("on")
    wd.execute("off")
    assert wd.lin.writes == [
        (CNTL0MOT_WIRE, [0x01, 0xdb]),
        (CNTL0MOT_WIRE, [0xcd, 0x0c]),
    ]


def test_execute_hal_uses_injected_read_response():
    wd = Watchdog(DryRunLin())
    wd.lin.read_responses[constants.st0mot] = [0x01, 0x00, 0x01]
    reply = wd.execute("hal")
    assert reply == "OK ret=0 data=['0x01', '0x00', '0x01']"


def test_execute_hal_defaults_to_zeros_when_not_injected():
    wd = Watchdog(DryRunLin())
    reply = wd.execute("hal")
    assert reply == "OK ret=0 data=['0x00', '0x00', '0x00']"


def test_execute_rpm_reply_includes_hex():
    wd = Watchdog(DryRunLin())
    wd.lin.read_responses[constants.st2mot] = [0x2c, 0x01]  # 300
    reply = wd.execute("rpm")
    assert reply == "OK ret=0 rpm=300 (hex=0x012c)"


def test_execute_rpm_negative_shows_twos_complement_hex():
    wd = Watchdog(DryRunLin())
    wd.lin.read_responses[constants.st2mot] = [0xd4, 0xfe]  # -300, per get_rpm
    reply = wd.execute("rpm")
    assert reply == "OK ret=0 rpm=-300 (hex=0xfed4)"


def test_execute_temp_reply_includes_hex():
    wd = Watchdog(DryRunLin())
    wd.lin.read_responses[constants.st1mot] = [0x10, 0x00]  # 16
    reply = wd.execute("temp")
    assert reply == "OK ret=0 temp=16 (hex=0x0010)"


def test_execute_current_parses_and_converts_to_amps():
    wd = Watchdog(DryRunLin())
    # raw val1=300 (0x2c, high bits 0x01), raw val2=100 (0x64, high bits
    # 0x00) -- matches currentsensor/firmware/main.cpp's data[0..3]
    # packing. Converted via linbus._adc_to_amps() (Vcc=5V, 2.5V=0A,
    # 100mV/A -- ACS712xLCTR-20A datasheet value).
    wd.lin.read_responses[constants.st0cur] = [0x2c, 0x01, 0x64, 0x00]
    reply = wd.execute("current")
    assert reply == "OK ret=0 val1=-10.35 val2=-20.12"


# --- Connection lifecycle: disconnect + idle timeout ---

def test_disconnect_stops_motor_immediately():
    wd = Watchdog(DryRunLin())
    wd.on_connect()
    wd.execute("speed 300")
    wd.lin.writes.clear()
    wd.on_disconnect()
    assert wd.lin.writes == [(CNTL3MOT_WIRE, [0x00, 0x00])]  # speed 0
    assert wd.last_commanded_speed == 0
    assert wd.last_command_time is None


def test_idle_check_does_nothing_with_no_connection():
    wd = Watchdog(DryRunLin())
    wd.check_idle()  # last_command_time is None (no client) -> no-op
    assert wd.lin.writes == []


def test_idle_check_does_nothing_right_after_a_command():
    wd = Watchdog(DryRunLin())
    wd.on_connect()
    wd.execute("hal")
    wd.check_idle()
    assert wd.lin.writes == []


def test_idle_timeout_stops_motor_when_stale():
    wd = Watchdog(DryRunLin())
    wd.on_connect()
    wd.execute("hal")
    wd.last_command_time -= (IDLE_TIMEOUT + 0.1)  # simulate elapsed time
    wd.check_idle()
    assert wd.stopped_for_idle is True
    assert wd.lin.writes == [(CNTL3MOT_WIRE, [0x00, 0x00])]  # speed 0


def test_idle_timeout_only_stops_once_not_every_tick():
    wd = Watchdog(DryRunLin())
    wd.on_connect()
    wd.last_command_time -= (IDLE_TIMEOUT + 0.1)
    wd.check_idle()
    wd.check_idle()
    wd.check_idle()
    assert len(wd.lin.writes) == 1  # not re-sent on every subsequent tick


def test_new_connection_resets_idle_state():
    wd = Watchdog(DryRunLin())
    wd.on_connect()
    wd.last_command_time -= (IDLE_TIMEOUT + 0.1)
    wd.check_idle()
    assert wd.stopped_for_idle is True
    wd.on_connect()  # a fresh client connects
    assert wd.stopped_for_idle is False
    assert wd.last_command_time is not None


# --- Stall check (interim, rpm-only, now fed by self-polling) ---

def test_stall_not_checked_while_speed_is_zero():
    wd = Watchdog(DryRunLin())
    wd.lin.read_responses[constants.st2mot] = [0x00, 0x00]  # rpm=0
    wd.poll_rpm()  # never commanded to move, rpm=0 is expected/fine
    assert wd.lin.writes == []


def test_stall_not_judged_during_grace_period():
    wd = Watchdog(DryRunLin())
    wd.execute("speed 300")
    wd.lin.writes.clear()
    wd.lin.read_responses[constants.st2mot] = [0x00, 0x00]  # rpm=0
    wd.poll_rpm()  # still within STALL_GRACE_PERIOD, not judged yet
    assert wd.lin.writes == []
    assert wd.last_commanded_speed == 300


def test_stall_detected_after_grace_period_if_rpm_still_zero():
    from watchdog import STALL_GRACE_PERIOD
    wd = Watchdog(DryRunLin())
    wd.execute("speed 300")
    wd.speed_became_nonzero_at -= (STALL_GRACE_PERIOD + 0.1)  # simulate elapsed time
    wd.lin.writes.clear()
    wd.lin.read_responses[constants.st2mot] = [0x00, 0x00]  # rpm=0
    wd.poll_rpm()
    assert wd.lin.writes == [(CNTL3MOT_WIRE, [0x00, 0x00])]  # stop sent
    assert wd.last_commanded_speed == 0


def test_no_stall_after_grace_period_if_rpm_nonzero():
    from watchdog import STALL_GRACE_PERIOD
    wd = Watchdog(DryRunLin())
    wd.execute("speed 300")
    wd.speed_became_nonzero_at -= (STALL_GRACE_PERIOD + 0.1)
    wd.lin.writes.clear()
    wd.lin.read_responses[constants.st2mot] = [0x2c, 0x01]  # rpm=300, moving
    wd.poll_rpm()
    assert wd.lin.writes == []  # no stall, no stop sent
    assert wd.last_commanded_speed == 300


def test_poll_rpm_works_with_no_client_connected():
    # Self-polling must not depend on last_command_time / an active
    # connection — it's a separate concern from the idle check.
    wd = Watchdog(DryRunLin())
    wd.execute("speed 300")
    wd.on_disconnect()  # no client connected anymore; motor already
    # stopped by on_disconnect(), so re-command it to test poll_rpm in
    # isolation without a connection:
    wd.last_commanded_speed = 300
    wd.speed_became_nonzero_at = 0  # long in the past -> past grace period
    wd.lin.writes.clear()
    wd.lin.read_responses[constants.st2mot] = [0x00, 0x00]
    wd.poll_rpm()
    assert wd.lin.writes == [(CNTL3MOT_WIRE, [0x00, 0x00])]
