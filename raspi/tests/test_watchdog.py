import pytest

from watchdog import validate, Watchdog, SPEED_MIN, SPEED_MAX, IDLE_TIMEOUT, PI_DELTA_MIN, PI_DELTA_MAX
from linbus import DryRunLin, MOTOR_INSTANCE_ID, CURRENT_INSTANCE_ID
from linaddresses import constants

# Unit tests only — pure logic, no sockets, no hardware. Runs anywhere,
# including natively on Windows. Integration tests (real Listener/Client
# over AF_UNIX) need Linux — see raspi/watchdog/CLAUDE.md's Test Suite
# section for why.

RANGE_ERROR = f"speed value out of range ({SPEED_MIN}..{SPEED_MAX})"
PI_RANGE_ERROR_P = f"p_delta out of range ({PI_DELTA_MIN}..{PI_DELTA_MAX})"
PI_RANGE_ERROR_I = f"i_delta out of range ({PI_DELTA_MIN}..{PI_DELTA_MAX})"

# Expected on-wire pid for motor commands: base pid combined with the one
# motor currently on the bus's strap-pin instance id — see linbus.py's
# TARGET_MOTOR_INSTANCE comment.
CNTL0MOT_WIRE = constants.cntl0mot | MOTOR_INSTANCE_ID
CNTL3MOT_WIRE = constants.cntl3mot | MOTOR_INSTANCE_ID
CNTL0CUR_WIRE = constants.cntl0cur | CURRENT_INSTANCE_ID


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
    ("pi 0.1 -0.05", (True, None)),
    (f"pi {PI_DELTA_MAX} {PI_DELTA_MIN}", (True, None)),
    ("pi 0 0", (True, None)),
    (f"pi {PI_DELTA_MAX + 0.01} 0", (False, PI_RANGE_ERROR_P)),
    (f"pi {PI_DELTA_MIN - 0.01} 0", (False, PI_RANGE_ERROR_P)),
    (f"pi 0 {PI_DELTA_MAX + 0.01}", (False, PI_RANGE_ERROR_I)),
    ("pi abc 0", (False, "p_delta/i_delta must be numbers")),
    ("pi 0.1", (False, "usage: pi <p_delta> <i_delta>")),
    ("pi 0.1 0.1 0.1", (False, "usage: pi <p_delta> <i_delta>")),
    ("hal", (True, None)),
    ("rpm", (True, None)),
    ("temp", (True, None)),
    ("current", (True, None)),
    ("errors", (True, None)),
    ("selftest", (True, None)),
    ("hal extra", (False, "usage: hal")),
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


def test_execute_pi_relays_to_dry_run_bus():
    wd = Watchdog(DryRunLin())
    assert wd.execute("pi 0.1 -0.05") == "OK"
    assert wd.lin.writes == [
        (CNTL0MOT_WIRE, [10, 251]),  # p_byte=10 (0.1*100), i_byte=-5 as unsigned (0.05*100)
    ]


def test_execute_pi_clamps_to_wire_extremes():
    wd = Watchdog(DryRunLin())
    assert wd.execute(f"pi {PI_DELTA_MAX} {PI_DELTA_MIN}") == "OK"
    assert wd.lin.writes == [(CNTL0MOT_WIRE, [127, 128])]


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


def test_execute_errors_decodes_two_complement_codes_and_names():
    wd = Watchdog(DryRunLin())
    # 0xfb = -5 (LIN_CHK_ERR, "CHK"), rest unused/no-error (0, "OK") --
    # matches currentsensor/firmware/main.cpp's errorstorage[8] on-wire
    # as raw int8_t bytes (two's complement).
    wd.lin.read_responses[constants.st1cur] = [0xfb, 0, 0, 0, 0, 0, 0, 0]
    reply = wd.execute("errors")
    assert reply == ("OK ret=0 codes=[-5, 0, 0, 0, 0, 0, 0, 0] "
                      "names=['CHK', 'OK', 'OK', 'OK', 'OK', 'OK', 'OK', 'OK']")


def test_execute_errors_defaults_to_no_errors_when_not_injected():
    wd = Watchdog(DryRunLin())
    reply = wd.execute("errors")
    assert reply == ("OK ret=0 codes=[0, 0, 0, 0, 0, 0, 0, 0] "
                      "names=['OK', 'OK', 'OK', 'OK', 'OK', 'OK', 'OK', 'OK']")


def test_execute_selftest_writes_inject_reset_csbadwrite_sabotage_then_bad_checksum_in_order():
    wd = Watchdog(DryRunLin())
    wd.execute("selftest")
    assert wd.lin.writes == [
        (CNTL0CUR_WIRE, [0x01, 0xab]),
        (CNTL0CUR_WIRE, [0xcd, 0x0c]),
        (CNTL0CUR_WIRE, [0x01, 0xab]),  # provoke_currentsensor_checksum_error()'s bad-checksum inject
        (CNTL0CUR_WIRE, [0xfa, 0x17]),
        (CNTL3MOT_WIRE, [0x00, 0x00]),  # provoke_checksum_error()'s speed-0 write
    ]


def test_execute_selftest_reads_and_decodes_st1cur_after_each_write():
    wd = Watchdog(DryRunLin())
    # DryRunLin has no real firmware state behind it, so all reads below
    # return the same injected value regardless of the writes above --
    # this test only exercises the read/decode plumbing, not real
    # inject-then-reset or provoke-then-catch state transitions (those
    # need real/dry-run hardware, see raspi/watchdog/CLAUDE.md's Test
    # Suite section).
    wd.lin.read_responses[constants.st1cur] = [0xfb, 0, 0, 0, 0, 0, 0, 0]
    wd.lin.read_responses[constants.st3mot] = [0x05, 0x00, 0x00, 0x00]  # timeout=5, checksum=0
    reply = wd.execute("selftest")
    assert reply == (
        "OK inject_ret=0 "
        "injected(ret=0 codes=[-5, 0, 0, 0, 0, 0, 0, 0] "
        "names=['CHK', 'OK', 'OK', 'OK', 'OK', 'OK', 'OK', 'OK']) "
        "reset_ret=0 "
        "after_reset(ret=0 codes=[-5, 0, 0, 0, 0, 0, 0, 0] "
        "names=['CHK', 'OK', 'OK', 'OK', 'OK', 'OK', 'OK', 'OK']) "
        "currentsensor_checksum_test("
        "motor_before(ret=0 timeout=5 checksum=0) "
        "bad_write_ret=0 "
        "currentsensor_after(ret=0 codes=[-5, 0, 0, 0, 0, 0, 0, 0] "
        "names=['CHK', 'OK', 'OK', 'OK', 'OK', 'OK', 'OK', 'OK']) "
        "motor_after(ret=0 timeout=5 checksum=0)) "
        "bushang_test(before(ret=0 timeout=5 checksum=0) "
        "arm_ret=0 trigger_ret=0 "
        "after(ret=0 timeout=5 checksum=0) "
        "currentsensor_after(ret=0 codes=[-5, 0, 0, 0, 0, 0, 0, 0] "
        "names=['CHK', 'OK', 'OK', 'OK', 'OK', 'OK', 'OK', 'OK'])) "
        "checksum_test(before(ret=0 timeout=5 checksum=0) "
        "bad_write_ret=0 "
        "after(ret=0 timeout=5 checksum=0))"
    )


def test_get_motor_counters_decodes_two_little_endian_uint16_fields():
    from linbus import get_motor_counters
    lin = DryRunLin()
    lin.read_responses[constants.st3mot] = [0x2c, 0x01, 0x03, 0x00]  # timeout=300, checksum=3
    ret, timeout_count, checksum_error_count = get_motor_counters(lin)
    assert (ret, timeout_count, checksum_error_count) == (0, 300, 3)


def test_provoke_checksum_error_writes_safe_speed_zero_via_bad_checksum():
    from linbus import provoke_checksum_error
    lin = DryRunLin()
    ret = provoke_checksum_error(lin)
    assert ret == 0
    assert lin.writes == [(CNTL3MOT_WIRE, [0x00, 0x00])]


def test_provoke_currentsensor_checksum_error_writes_inject_bytes_via_bad_checksum():
    from linbus import provoke_currentsensor_checksum_error
    lin = DryRunLin()
    ret = provoke_currentsensor_checksum_error(lin)
    assert ret == 0
    assert lin.writes == [(CNTL0CUR_WIRE, [0x01, 0xab])]


def test_provoke_bus_hang_timeout_arms_sabotage_and_triggers_current_read():
    from linbus import provoke_bus_hang_timeout
    lin = DryRunLin()
    ret_arm, ret_trigger = provoke_bus_hang_timeout(lin)
    assert (ret_arm, ret_trigger) == (0, 0)  # dry-run: no real failure to see
    assert lin.writes == [(CNTL0CUR_WIRE, [0xfa, 0x17])]


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


def test_poll_rpm_caches_last_known_rpm():
    wd = Watchdog(DryRunLin())
    wd.lin.read_responses[constants.st2mot] = [0x2c, 0x01]  # rpm=300
    wd.poll_rpm()
    assert wd.last_known_rpm == 300


# --- Upper-layer stall *signature* (current while rpm=0) -- observe-only,
# see watchdog/CLAUDE.md's Two-Layer Safety Check section: logs, does not
# stop the motor yet.

def test_poll_current_logs_but_does_not_stop_when_signature_present(caplog):
    wd = Watchdog(DryRunLin())
    wd.last_known_rpm = 0
    # raw=522 -> ~0.49A, above CURRENT_STALL_THRESHOLD (0.15A)
    wd.lin.read_responses[constants.st0cur] = [10, 2, 0, 2]
    wd.poll_current()
    assert wd.lin.writes == []  # observe-only -- never stops the motor
    assert "STALL SIGNATURE" in caplog.text


def test_poll_current_silent_when_below_threshold(caplog):
    wd = Watchdog(DryRunLin())
    wd.last_known_rpm = 0
    # raw=512 -> 0.0A, below threshold
    wd.lin.read_responses[constants.st0cur] = [0, 2, 0, 2]
    wd.poll_current()
    assert "STALL SIGNATURE" not in caplog.text


def test_poll_current_silent_when_rpm_nonzero(caplog):
    # Same current reading as the triggering case above, but the motor
    # is actually turning -- not a stall signature, current is expected.
    wd = Watchdog(DryRunLin())
    wd.last_known_rpm = 300
    wd.lin.read_responses[constants.st0cur] = [10, 2, 0, 2]
    wd.poll_current()
    assert "STALL SIGNATURE" not in caplog.text


def test_poll_current_silent_when_last_known_rpm_unset(caplog):
    # last_known_rpm is None until poll_rpm() has run at least once --
    # must not be mistaken for rpm==0.
    wd = Watchdog(DryRunLin())
    wd.lin.read_responses[constants.st0cur] = [10, 2, 0, 2]
    wd.poll_current()
    assert "STALL SIGNATURE" not in caplog.text


# Note: --debug tracing (timestamped ->/<- bus-call logging) moved to
# linbus.Lin itself (see raspi/tests/test_linbus.py's _log_source()/
# _log_pid_name() tests) -- Watchdog no longer has its own debug flag or
# per-tick prints.
