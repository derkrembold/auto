import pytest

from watchdog import (validate, Watchdog, SPEED_MIN, SPEED_MAX, IDLE_TIMEOUT,
                      PI_DELTA_MIN, PI_DELTA_MAX, PULSE_SPEED_MIN, PULSE_SPEED_MAX,
                      MOTOR_INSTANCE_MIN, MOTOR_INSTANCE_MAX,
                      CURRENT_INSTANCE_MIN, CURRENT_INSTANCE_MAX)
from linbus import DryRunLin
from linaddresses import constants

# Unit tests only — pure logic, no sockets, no hardware. Runs anywhere,
# including natively on Windows. Integration tests (real Listener/Client
# over AF_UNIX) need Linux — see raspi/watchdog/CLAUDE.md's Test Suite
# section for why.

RANGE_ERROR = f"speed value out of range ({SPEED_MIN}..{SPEED_MAX})"
PI_RANGE_ERROR_P = f"p_delta out of range ({PI_DELTA_MIN}..{PI_DELTA_MAX})"
PI_RANGE_ERROR_I = f"i_delta out of range ({PI_DELTA_MIN}..{PI_DELTA_MAX})"
PULSE_RANGE_ERROR = f"pulse value out of range ({PULSE_SPEED_MIN}..{PULSE_SPEED_MAX})"
MOTOR_INSTANCE_ERROR = f"motor instance out of range ({MOTOR_INSTANCE_MIN}..{MOTOR_INSTANCE_MAX})"
CURRENT_INSTANCE_ERROR = f"current sensor instance out of range ({CURRENT_INSTANCE_MIN}..{CURRENT_INSTANCE_MAX})"

# Expected on-wire pid for every dry-run test below -- all target
# MONITORED_MOTOR_INSTANCE/MONITORED_CURRENT_INSTANCE (0), i.e.
# "motor 0"/"sensor 0" in every command string, which is also what
# Watchdog's own self-polling/stall-check/overcurrent-stop act on (see
# watchdog.py's MONITORED_MOTOR_INSTANCE comment). Multi-instance dry-run
# coverage (e.g. does "speed 1 500" reach a *different* wire pid) is in
# the dedicated multi-instance section further down.
MOTOR0_ID = constants.motor_instances[0]
CURRENT0_ID = constants.current_instances[0]
CNTL0MOT_WIRE = constants.cntl0mot | MOTOR0_ID
CNTL1MOT_WIRE = constants.cntl1mot | MOTOR0_ID
CNTL2MOT_WIRE = constants.cntl2mot | MOTOR0_ID
CNTL3MOT_WIRE = constants.cntl3mot | MOTOR0_ID
CNTL0CUR_WIRE = constants.cntl0cur | CURRENT0_ID


@pytest.mark.parametrize("command,expected", [
    ("speed 0 300", (True, None)),
    ("speed 0 -300", (True, None)),
    ("speed 0 0", (True, None)),
    ("speed 3 300", (True, None)),  # highest valid motor instance
    (f"speed 0 {SPEED_MAX}", (True, None)),
    (f"speed 0 {SPEED_MIN}", (True, None)),
    (f"speed 0 {SPEED_MAX + 1}", (False, RANGE_ERROR)),
    (f"speed 0 {SPEED_MIN - 1}", (False, RANGE_ERROR)),
    ("speed 0 abc", (False, "speed value must be an integer")),
    ("speed 4 300", (False, MOTOR_INSTANCE_ERROR)),  # one past the max
    ("speed -1 300", (False, MOTOR_INSTANCE_ERROR)),
    ("speed abc 300", (False, "motor instance must be an integer")),
    ("speed", (False, "usage: speed <motor_instance> <value>")),
    ("speed 0", (False, "usage: speed <motor_instance> <value>")),
    ("speed 0 1 2", (False, "usage: speed <motor_instance> <value>")),
    ("pi 0 0.1 -0.05", (True, None)),
    (f"pi 0 {PI_DELTA_MAX} {PI_DELTA_MIN}", (True, None)),
    ("pi 0 0 0", (True, None)),
    (f"pi 0 {PI_DELTA_MAX + 0.01} 0", (False, PI_RANGE_ERROR_P)),
    (f"pi 0 {PI_DELTA_MIN - 0.01} 0", (False, PI_RANGE_ERROR_P)),
    (f"pi 0 0 {PI_DELTA_MAX + 0.01}", (False, PI_RANGE_ERROR_I)),
    ("pi 4 0.1 0", (False, MOTOR_INSTANCE_ERROR)),
    ("pi 0 abc 0", (False, "p_delta/i_delta must be numbers")),
    ("pi 0 0.1", (False, "usage: pi <motor_instance> <p_delta> <i_delta>")),
    ("pi 0 0.1 0.1 0.1", (False, "usage: pi <motor_instance> <p_delta> <i_delta>")),
    ("pulse 0 300", (True, None)),
    ("pulse 0 -300", (True, None)),
    (f"pulse 0 {PULSE_SPEED_MAX}", (True, None)),
    (f"pulse 0 {PULSE_SPEED_MIN}", (True, None)),
    (f"pulse 0 {PULSE_SPEED_MAX + 1}", (False, PULSE_RANGE_ERROR)),
    (f"pulse 0 {PULSE_SPEED_MIN - 1}", (False, PULSE_RANGE_ERROR)),
    ("pulse 0 abc", (False, "pulse value must be an integer")),
    ("pulse 4 300", (False, MOTOR_INSTANCE_ERROR)),
    ("pulse", (False, "usage: pulse <motor_instance> <value>")),
    ("hal 0", (True, None)),
    ("hal 3", (True, None)),
    ("hal 4", (False, MOTOR_INSTANCE_ERROR)),
    ("hal", (False, "usage: hal <motor_instance>")),
    ("hal 0 extra", (False, "usage: hal <motor_instance>")),
    ("rpm 0", (True, None)),
    ("temp 0", (True, None)),
    ("current 0", (True, None)),
    ("current 1", (True, None)),  # highest valid current-sensor instance
    ("current 2", (False, CURRENT_INSTANCE_ERROR)),
    ("current", (False, "usage: current <current_instance>")),
    ("errors 0", (True, None)),
    ("errors 2", (False, CURRENT_INSTANCE_ERROR)),
    ("selftest", (True, None)),  # NOT yet instance-parameterized, see watchdog.py
    ("kickcount 0", (True, None)),
    ("reset 0", (True, None)),
    ("reset 0 extra", (False, "usage: reset <motor_instance>")),
    ("reset", (False, "usage: reset <motor_instance>")),
    ("status 0", (True, None)),
    ("status 0 extra", (False, "usage: status <motor_instance>")),
    ("status", (False, "usage: status <motor_instance>")),
    ("burst 0 -500 10 1000 5", (True, None)),
    (f"burst 0 {PULSE_SPEED_MIN} 0 {PULSE_SPEED_MAX} 0", (True, None)),
    (f"burst 0 {PULSE_SPEED_MIN - 1} 10 100 5",
     (False, f"value1 out of range ({PULSE_SPEED_MIN}..{PULSE_SPEED_MAX})")),
    (f"burst 0 -100 10 {PULSE_SPEED_MAX + 1} 5",
     (False, f"value2 out of range ({PULSE_SPEED_MIN}..{PULSE_SPEED_MAX})")),
    ("burst 0 -500 -10 1000 5", (False, "pause1_ms/pause2_ms must be non-negative")),
    ("burst 0 -500 10 1000 -5", (False, "pause1_ms/pause2_ms must be non-negative")),
    ("burst 0 abc 10 1000 5",
     (False, "burst usage: value1/value2 must be integers, pause1_ms/pause2_ms must be numbers")),
    ("burst 4 -500 10 1000 5", (False, MOTOR_INSTANCE_ERROR)),
    ("burst 0 -500 10 1000",
     (False, "usage: burst <motor_instance> <value1> <pause1_ms> <value2> <pause2_ms>")),
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
    assert wd.execute("speed 0 300") == "OK"
    assert len(wd.lin.writes) == 1
    address, data = wd.lin.writes[0]
    assert address == CNTL3MOT_WIRE
    assert data == [0x01, 0x2c]  # struct.pack('>h', 300)


def test_execute_pulse_relays_to_dry_run_bus():
    wd = Watchdog(DryRunLin())
    assert wd.execute("pulse 0 300") == "OK"
    assert len(wd.lin.writes) == 1
    address, data = wd.lin.writes[0]
    assert address == CNTL1MOT_WIRE
    assert data == [0x01, 0x2c]  # struct.pack('>h', 300)


def test_execute_pulse_does_not_touch_stall_check_state():
    # A single open-loop probe pulse, unlike "speed", must not feed the
    # rpm-based stall check -- see watchdog.py's _dispatch() comment.
    wd = Watchdog(DryRunLin())
    wd.last_commanded_speed = 300
    wd.speed_became_nonzero_at = 12345.0
    assert wd.execute("pulse 0 -300") == "OK"
    assert wd.last_commanded_speed == 300
    assert wd.speed_became_nonzero_at == 12345.0


def test_execute_burst_relays_two_pulses_in_order():
    wd = Watchdog(DryRunLin())
    assert wd.execute("burst 0 -500 0 1000 0") == "OK"
    assert len(wd.lin.writes) == 2
    address1, data1 = wd.lin.writes[0]
    address2, data2 = wd.lin.writes[1]
    assert address1 == CNTL1MOT_WIRE
    assert address2 == CNTL1MOT_WIRE
    assert data1 == [0xfe, 0x0c]  # struct.pack('>h', -500)
    assert data2 == [0x03, 0xe8]  # struct.pack('>h', 1000)


def test_execute_burst_does_not_touch_stall_check_state():
    wd = Watchdog(DryRunLin())
    wd.last_commanded_speed = 300
    wd.speed_became_nonzero_at = 12345.0
    assert wd.execute("burst 0 -500 0 1000 0") == "OK"
    assert wd.last_commanded_speed == 300
    assert wd.speed_became_nonzero_at == 12345.0


def test_execute_reset_relays_to_dry_run_bus():
    wd = Watchdog(DryRunLin())
    assert wd.execute("reset 0") == "OK"
    assert wd.lin.writes == [(CNTL2MOT_WIRE, [0, 0, 0, 0, 0, 0])]


def test_execute_reset_clears_stall_check_state():
    # controlvariableinput going to 0 firmware-side is the same
    # real-world effect as "speed 0" -- see watchdog.py's _dispatch()
    # comment for why the Pi-side bookkeeping is updated to match.
    wd = Watchdog(DryRunLin())
    wd.last_commanded_speed = 300
    wd.speed_became_nonzero_at = 12345.0
    assert wd.execute("reset 0") == "OK"
    assert wd.last_commanded_speed == 0
    assert wd.speed_became_nonzero_at is None


def test_execute_pi_relays_to_dry_run_bus():
    wd = Watchdog(DryRunLin())
    assert wd.execute("pi 0 0.1 -0.05") == "OK"
    assert wd.lin.writes == [
        (CNTL0MOT_WIRE, [10, 251]),  # p_byte=10 (0.1*100), i_byte=-5 as unsigned (0.05*100)
    ]


def test_execute_pi_clamps_to_wire_extremes():
    wd = Watchdog(DryRunLin())
    assert wd.execute(f"pi 0 {PI_DELTA_MAX} {PI_DELTA_MIN}") == "OK"
    assert wd.lin.writes == [(CNTL0MOT_WIRE, [127, 128])]


def test_execute_hal_uses_injected_read_response():
    wd = Watchdog(DryRunLin())
    wd.lin.read_responses[constants.st0mot] = [0x01, 0x00, 0x01]
    reply = wd.execute("hal 0")
    assert reply == "OK ret=0 data=['0x01', '0x00', '0x01']"


def test_execute_hal_defaults_to_zeros_when_not_injected():
    wd = Watchdog(DryRunLin())
    reply = wd.execute("hal 0")
    assert reply == "OK ret=0 data=['0x00', '0x00', '0x00']"


def test_execute_rpm_reply_includes_hex():
    wd = Watchdog(DryRunLin())
    wd.lin.read_responses[constants.st2mot] = [0x2c, 0x01]  # 300
    reply = wd.execute("rpm 0")
    assert reply == "OK ret=0 rpm=300 (hex=0x012c)"


def test_execute_rpm_negative_shows_twos_complement_hex():
    wd = Watchdog(DryRunLin())
    wd.lin.read_responses[constants.st2mot] = [0xd4, 0xfe]  # -300, per get_rpm
    reply = wd.execute("rpm 0")
    assert reply == "OK ret=0 rpm=-300 (hex=0xfed4)"


def test_execute_temp_reply_includes_hex():
    wd = Watchdog(DryRunLin())
    wd.lin.read_responses[constants.st1mot] = [0x10, 0x00]  # 16
    reply = wd.execute("temp 0")
    assert reply == "OK ret=0 temp=16 (hex=0x0010)"


def test_execute_kickcount_reads_data3():
    wd = Watchdog(DryRunLin())
    wd.lin.read_responses[constants.st3mot] = [0x00, 0x00, 0x01, 0x07]
    reply = wd.execute("kickcount 0")
    assert reply == "OK ret=0 kickcount=7"


def test_execute_status_decodes_all_fields():
    wd = Watchdog(DryRunLin())
    # timeout=300 (0x012c), checksum=3, kickstart=7, sys_error=-65 (0xbf
    # two's complement) -- same STALL_TIM_ERR value used elsewhere in
    # this file, confirms the negative decoding survives execute() too.
    wd.lin.read_responses[constants.st3mot] = [0x2c, 0x01, 0x03, 0x07, 0xbf, 0x00]
    reply = wd.execute("status 0")
    assert reply == ("OK ret=0 timeout=300 checksum=3 kickstart=7 "
                      "sys_error=-65")


def test_execute_current_parses_and_converts_to_amps():
    wd = Watchdog(DryRunLin())
    # raw val1=300 (0x2c, high bits 0x01), raw val2=100 (0x64, high bits
    # 0x00) -- matches currentsensor/firmware/main.cpp's data[0..3]
    # packing. Converted via linbus._adc_to_amps() (Vcc=5V, 2.5V=0A,
    # 100mV/A -- ACS712xLCTR-20A datasheet value).
    wd.lin.read_responses[constants.st0cur] = [0x2c, 0x01, 0x64, 0x00]
    reply = wd.execute("current 0")
    assert reply == "OK ret=0 val1=-10.35 val2=-20.12"


def test_execute_errors_decodes_two_complement_codes_and_names():
    wd = Watchdog(DryRunLin())
    # 0xfb = -5 (LIN_CHK_ERR, "CHK"), rest unused/no-error (0, "OK") --
    # matches currentsensor/firmware/main.cpp's errorstorage[8] on-wire
    # as raw int8_t bytes (two's complement).
    wd.lin.read_responses[constants.st1cur] = [0xfb, 0, 0, 0, 0, 0, 0, 0]
    reply = wd.execute("errors 0")
    assert reply == ("OK ret=0 codes=[-5, 0, 0, 0, 0, 0, 0, 0] "
                      "names=['CHK', 'OK', 'OK', 'OK', 'OK', 'OK', 'OK', 'OK']")


def test_execute_errors_defaults_to_no_errors_when_not_injected():
    wd = Watchdog(DryRunLin())
    reply = wd.execute("errors 0")
    assert reply == ("OK ret=0 codes=[0, 0, 0, 0, 0, 0, 0, 0] "
                      "names=['OK', 'OK', 'OK', 'OK', 'OK', 'OK', 'OK', 'OK']")


def test_execute_speed_different_instance_reaches_different_wire_pid():
    # Multi-instance sanity check (2026-09-11): "speed 1 300" must reach
    # motor instance 1's own wire pid, not instance 0's -- confirms the
    # instance argument actually changes what's on the bus, not just that
    # it's accepted syntactically.
    wd = Watchdog(DryRunLin())
    assert wd.execute("speed 1 300") == "OK"
    address, data = wd.lin.writes[0]
    assert address == (constants.cntl3mot | constants.motor_instances[1])
    assert address != CNTL3MOT_WIRE
    assert data == [0x01, 0x2c]
    # Commanding instance 1 must not perturb instance 0's own stall-check
    # bookkeeping (MONITORED_MOTOR_INSTANCE is 0) -- see _dispatch()'s
    # comment.
    assert wd.last_commanded_speed == 0
    assert wd.speed_became_nonzero_at is None


def test_execute_current_instance_1_is_accepted_and_resolves_a_different_wire_id():
    wd = Watchdog(DryRunLin())
    # DryRunLin's read() is keyed by base address regardless of instance
    # (see its own docstring) -- the reply content is identical for
    # instance 0 or 1, so this only confirms "current 1" is accepted and
    # dispatched, not stuck at "unknown command"/a validate() rejection.
    assert wd.execute("current 1") == "OK ret=0 val1=-25.00 val2=-25.00"
    # The actual wire-id resolution itself (base pid | instance) is
    # exercised directly here, since DryRunLin.read() doesn't log reads
    # the way it logs writes.
    from linbus import _current_wire_id
    assert _current_wire_id(1) == constants.current_instances[1]
    assert _current_wire_id(1) != _current_wire_id(0)


def test_execute_selftest_writes_inject_reset_csbadwrite_sabotage_then_bad_checksum_in_order():
    wd = Watchdog(DryRunLin())
    wd.execute("selftest")
    assert wd.lin.writes == [
        (CNTL0CUR_WIRE, [0x01, 0xab]),
        (CNTL0CUR_WIRE, [0xcd, 0x0c]),
        (CNTL0CUR_WIRE, [0x01, 0xab]),  # provoke_currentsensor_checksum_error()'s bad-checksum inject
        (CNTL0CUR_WIRE, [0xfa, 0x17]),
        (CNTL3MOT_WIRE, [0x00, 0x00]),  # provoke_checksum_error()'s speed-0 write
        (CNTL2MOT_WIRE, [0, 0, 0, 0, 0, 0]),  # reset_motor(), part 4
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
    # timeout=5, checksum=0, kickstart=0, sys_error=0, reserved=0 --
    # 6 bytes since the 2026-09-07 st3mot extension (see linbus.py's
    # get_motor_status()).
    wd.lin.read_responses[constants.st3mot] = [0x05, 0x00, 0x00, 0x00, 0x00, 0x00]
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
        "after(ret=0 timeout=5 checksum=0)) "
        "reset_test(before(ret=0 timeout=5 checksum=0 kickstart=0 sys_error=0) "
        "reset_ret=0 "
        "after(ret=0 timeout=5 checksum=0 kickstart=0 sys_error=0))"
    )


def test_get_motor_counters_decodes_timeout_uint16_and_checksum_byte():
    from linbus import get_motor_counters
    lin = DryRunLin()
    # data[3] (0x07) is kickStartCount since 2026-08-27 -- not part of
    # checksum_error_count anymore, see get_kick_start_count() below.
    lin.read_responses[constants.st3mot] = [0x2c, 0x01, 0x03, 0x07]  # timeout=300, checksum=3
    ret, timeout_count, checksum_error_count = get_motor_counters(lin, 0)
    assert (ret, timeout_count, checksum_error_count) == (0, 300, 3)


def test_get_kick_start_count_decodes_data3():
    from linbus import get_kick_start_count
    lin = DryRunLin()
    lin.read_responses[constants.st3mot] = [0x2c, 0x01, 0x03, 0x07]
    ret, kick_start_count = get_kick_start_count(lin, 0)
    assert (ret, kick_start_count) == (0, 7)


def test_get_motor_status_decodes_all_six_bytes():
    from linbus import get_motor_status
    lin = DryRunLin()
    # timeout=300, checksum=3, kickstart=7, sys_error=0 (MOT_OK), reserved=0
    lin.read_responses[constants.st3mot] = [0x2c, 0x01, 0x03, 0x07, 0x00, 0x00]
    result = get_motor_status(lin, 0)
    assert result == (0, 300, 3, 7, 0)


def test_get_motor_status_decodes_negative_sys_error():
    from linbus import get_motor_status
    lin = DryRunLin()
    # sys_error=0xbf -- two's complement for -65 (errors.h's STALL_TIM_ERR)
    lin.read_responses[constants.st3mot] = [0x00, 0x00, 0x00, 0x00, 0xbf, 0x00]
    result = get_motor_status(lin, 0)
    assert result == (0, 0, 0, 0, -65)


def test_provoke_checksum_error_writes_safe_speed_zero_via_bad_checksum():
    from linbus import provoke_checksum_error
    lin = DryRunLin()
    ret = provoke_checksum_error(lin, 0)
    assert ret == 0
    assert lin.writes == [(CNTL3MOT_WIRE, [0x00, 0x00])]


def test_provoke_currentsensor_checksum_error_writes_inject_bytes_via_bad_checksum():
    from linbus import provoke_currentsensor_checksum_error
    lin = DryRunLin()
    ret = provoke_currentsensor_checksum_error(lin, 0)
    assert ret == 0
    assert lin.writes == [(CNTL0CUR_WIRE, [0x01, 0xab])]


def test_provoke_bus_hang_timeout_arms_sabotage_and_triggers_current_read():
    from linbus import provoke_bus_hang_timeout
    lin = DryRunLin()
    ret_arm, ret_trigger = provoke_bus_hang_timeout(lin, 0)
    assert (ret_arm, ret_trigger) == (0, 0)  # dry-run: no real failure to see
    assert lin.writes == [(CNTL0CUR_WIRE, [0xfa, 0x17])]


# --- Connection lifecycle: disconnect + idle timeout ---

def test_disconnect_stops_motor_immediately():
    wd = Watchdog(DryRunLin())
    wd.on_connect()
    wd.execute("speed 0 300")
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
    wd.execute("hal 0")
    wd.check_idle()
    assert wd.lin.writes == []


def test_idle_timeout_stops_motor_when_stale():
    wd = Watchdog(DryRunLin())
    wd.on_connect()
    wd.execute("hal 0")
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
    wd.execute("speed 0 300")
    wd.lin.writes.clear()
    wd.lin.read_responses[constants.st2mot] = [0x00, 0x00]  # rpm=0
    wd.poll_rpm()  # still within STALL_GRACE_PERIOD, not judged yet
    assert wd.lin.writes == []
    assert wd.last_commanded_speed == 300


def test_stall_detected_after_grace_period_if_rpm_still_zero():
    from watchdog import STALL_GRACE_PERIOD
    wd = Watchdog(DryRunLin())
    wd.execute("speed 0 300")
    wd.speed_became_nonzero_at -= (STALL_GRACE_PERIOD + 0.1)  # simulate elapsed time
    wd.lin.writes.clear()
    wd.lin.read_responses[constants.st2mot] = [0x00, 0x00]  # rpm=0
    wd.poll_rpm()
    assert wd.lin.writes == [(CNTL3MOT_WIRE, [0x00, 0x00])]  # stop sent
    assert wd.last_commanded_speed == 0


def test_no_stall_after_grace_period_if_rpm_nonzero():
    from watchdog import STALL_GRACE_PERIOD
    wd = Watchdog(DryRunLin())
    wd.execute("speed 0 300")
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
    wd.execute("speed 0 300")
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


# --- Overcurrent hard stop (added 2026-09-10) -- unlike the stall
# signature above, this one DOES stop the motor, and acts regardless of
# rpm. st0cur raw encoding: val1 = data[0] | ((data[1] & 3) << 8),
# val2 = data[2] | ((data[3] & 3) << 8); _adc_to_amps(901) ~= 19.0A
# (over the 15A threshold), _adc_to_amps(696) ~= 9.0A (under it).

def test_poll_current_hard_stops_on_overcurrent_val1(caplog):
    wd = Watchdog(DryRunLin())
    wd.lin.read_responses[constants.st0cur] = [133, 3, 0, 2]  # val1 ~19A, val2 ~0A
    wd.poll_current()
    assert wd.lin.writes == [(CNTL3MOT_WIRE, [0x00, 0x00])]  # speed 0 sent
    assert "OVERCURRENT" in caplog.text and "val1" in caplog.text
    assert wd.last_commanded_speed == 0


def test_poll_current_hard_stops_on_overcurrent_val2(caplog):
    wd = Watchdog(DryRunLin())
    wd.lin.read_responses[constants.st0cur] = [10, 2, 133, 3]  # val1 ~0.5A, val2 ~19A
    wd.poll_current()
    assert wd.lin.writes == [(CNTL3MOT_WIRE, [0x00, 0x00])]
    assert "OVERCURRENT" in caplog.text and "val2" in caplog.text


def test_poll_current_overcurrent_stops_even_when_rpm_nonzero(caplog):
    # Contrast with the stall-signature check, which only fires at rpm==0.
    # A jammed wheel while the vehicle is moving is still an overcurrent.
    wd = Watchdog(DryRunLin())
    wd.last_known_rpm = 1000
    wd.lin.read_responses[constants.st0cur] = [133, 3, 0, 2]  # val1 ~19A
    wd.poll_current()
    assert wd.lin.writes == [(CNTL3MOT_WIRE, [0x00, 0x00])]
    assert "OVERCURRENT" in caplog.text


def test_poll_current_no_hard_stop_below_overcurrent(caplog):
    wd = Watchdog(DryRunLin())
    wd.last_known_rpm = 300
    wd.lin.read_responses[constants.st0cur] = [184, 2, 184, 2]  # both ~9A, under 15A
    wd.poll_current()
    assert wd.lin.writes == []
    assert "OVERCURRENT" not in caplog.text


def test_poll_current_hard_stops_on_negative_overcurrent(caplog):
    # Motor wiring polarity is unknown -- an overcurrent shows up as
    # either sign. _adc_to_amps(123) ~= -19.0A, past the 15A magnitude.
    wd = Watchdog(DryRunLin())
    wd.last_known_rpm = 300
    wd.lin.read_responses[constants.st0cur] = [123, 0, 0, 2]  # val1 ~-19A
    wd.poll_current()
    assert wd.lin.writes == [(CNTL3MOT_WIRE, [0x00, 0x00])]
    assert "OVERCURRENT" in caplog.text


# Note: --debug tracing (timestamped ->/<- bus-call logging) moved to
# linbus.Lin itself (see raspi/tests/test_linbus.py's _log_source()/
# _log_pid_name() tests) -- Watchdog no longer has its own debug flag or
# per-tick prints.
