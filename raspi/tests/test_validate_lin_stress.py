import pytest

from validate_lin_stress import (
    run, parse_args, _parse_status, _parse_error_codes, _status_delta, _is_ok_reply,
    MOTOR_INSTANCES, CURRENT_INSTANCE, DURATION_S, SECONDARY_TICK_RATE_DEFAULT,
)


class _FakeClock:
    # Same shared-state monotonic()/sleep() pattern as
    # test_capture_step_response.py's _FakeClock -- lets run()'s real
    # scheduling logic execute exactly as it would with a real clock,
    # just instantly instead of over real wall-clock seconds.
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _status_reply(timeout=0, checksum=0, kickstart=0, sys_error=0, ret=0):
    return f"OK ret={ret} timeout={timeout} checksum={checksum} kickstart={kickstart} sys_error={sys_error}"


def _errors_reply(codes=(0, 0, 0, 0, 0, 0, 0, 0), ret=0):
    return f"OK ret={ret} codes={list(codes)} names={list(codes)}"


class _FakeConn:
    """Replies keyed by the exact command string first, falling back to
    just the verb, falling back to a stable default per verb -- lets a
    test override one specific instance's replies (e.g. "status 0") with
    a list to pop from (simulating a changing counter over the run)
    without disturbing every other command sharing the same verb."""

    def __init__(self, replies=None):
        self.sent = []
        self.replies = replies or {}

    def send(self, command):
        self.sent.append(command)
        self._pending_command = command

    def recv(self):
        command = self._pending_command
        verb = command.split()[0]
        for key in (command, verb):
            if key in self.replies:
                queue = self.replies[key]
                return queue.pop(0) if len(queue) > 1 else queue[0]
        if verb == "reset":
            return "OK"
        if verb == "speed":
            return "OK"
        if verb == "rpm":
            return "OK ret=0 rpm=0 (hex=0x0000)"
        if verb == "status":
            return _status_reply()
        if verb == "hal":
            return "OK ret=0 data=['0x01', '0x00', '0x01']"
        if verb == "current":
            return "OK ret=0 val1=0.00 val2=0.00"
        if verb == "errors":
            return _errors_reply()
        raise AssertionError(f"unexpected command: {command}")


# --- _is_ok_reply -----------------------------------------------------

def test_is_ok_reply_true_for_bare_ok_speed_reset_style():
    assert _is_ok_reply("OK") is True


def test_is_ok_reply_true_for_ret0_read_style():
    assert _is_ok_reply(_status_reply()) is True
    assert _is_ok_reply("OK ret=0 rpm=0 (hex=0x0000)") is True


def test_is_ok_reply_false_for_nonzero_ret():
    assert _is_ok_reply("OK ret=-5 rpm=None (hex=None)") is False


def test_is_ok_reply_false_for_garbage():
    assert _is_ok_reply("ERR something") is False
    assert _is_ok_reply("") is False


# --- pure parsers -----------------------------------------------------

def test_parse_status_extracts_all_fields():
    result = _parse_status(_status_reply(timeout=3, checksum=1, kickstart=5, sys_error=2))
    assert result == {"ret": 0, "timeout": 3, "checksum": 1, "kickstart": 5, "sys_error": 2}


def test_parse_status_returns_none_on_unparseable_reply():
    assert _parse_status("ERR something went wrong") is None


def test_parse_error_codes_extracts_list():
    assert _parse_error_codes(_errors_reply(codes=(0, -5, 0, 0, 0, 0, 0, 0))) == [0, -5, 0, 0, 0, 0, 0, 0]


def test_parse_error_codes_returns_none_on_nonzero_ret():
    assert _parse_error_codes(_errors_reply(ret=-5)) is None


def test_parse_error_codes_returns_none_on_unparseable_reply():
    assert _parse_error_codes("ERR timeout") is None


def test_status_delta_computes_field_differences():
    before = {"ret": 0, "timeout": 1, "checksum": 0, "kickstart": 2, "sys_error": 0}
    after = {"ret": 0, "timeout": 3, "checksum": 1, "kickstart": 2, "sys_error": 0}
    assert _status_delta(before, after) == {"timeout": 2, "checksum": 1, "kickstart": 0}


def test_status_delta_none_if_either_side_unparseable():
    before = {"ret": 0, "timeout": 1, "checksum": 0, "kickstart": 2, "sys_error": 0}
    assert _status_delta(before, None) is None
    assert _status_delta(None, before) is None


# --- run() scheduling ----------------------------------------------------

def test_run_sends_reset_for_both_motors_first():
    clock = _FakeClock()
    conn = _FakeConn()
    run(tick_rate=10.0, duration=1.0, conn=conn, sleep_fn=clock.sleep, clock_fn=clock.monotonic)
    assert conn.sent[0] == "reset 0"
    assert conn.sent[1] == "reset 1"


def test_run_reads_baseline_status_and_errors_after_reset():
    clock = _FakeClock()
    conn = _FakeConn()
    run(tick_rate=10.0, duration=1.0, conn=conn, sleep_fn=clock.sleep, clock_fn=clock.monotonic)
    # after the two resets: status 0, status 1, errors <current instance>
    assert conn.sent[2] == "status 0"
    assert conn.sent[3] == "status 1"
    assert conn.sent[4] == f"errors {CURRENT_INSTANCE}"


def test_run_main_tick_hits_both_motors_with_speed0_rpm_status():
    clock = _FakeClock()
    conn = _FakeConn()
    rows, _ = run(tick_rate=1.0, duration=1.0, conn=conn, sleep_fn=clock.sleep, clock_fn=clock.monotonic)
    commands = [r["command"] for r in rows]
    for instance in MOTOR_INSTANCES:
        assert f"speed {instance} 0" in commands
        assert f"rpm {instance}" in commands
        assert f"status {instance}" in commands


def test_run_main_tick_fires_expected_number_of_times():
    clock = _FakeClock()
    conn = _FakeConn()
    rows, _ = run(tick_rate=1.0, duration=5.0, conn=conn, sleep_fn=clock.sleep, clock_fn=clock.monotonic)
    speed0_count = sum(1 for r in rows if r["command"] == "speed 0 0")
    # ticks at t=0,1,2,3,4 -- 5 firings in a 5s window at 1s rate
    assert speed0_count == 5


def test_run_secondary_tick_fires_hal_current_errors():
    clock = _FakeClock()
    conn = _FakeConn()
    rows, _ = run(tick_rate=100.0, secondary_tick_rate=1.0, duration=3.0,
                   conn=conn, sleep_fn=clock.sleep, clock_fn=clock.monotonic)
    commands = [r["command"] for r in rows]
    for instance in MOTOR_INSTANCES:
        assert f"hal {instance}" in commands
    assert f"current {CURRENT_INSTANCE}" in commands
    assert f"errors {CURRENT_INSTANCE}" in commands


def test_run_secondary_tick_rate_decoupled_from_main_tick_rate():
    clock = _FakeClock()
    conn = _FakeConn()
    # main tick fast (0.5s), secondary slow (2s) over 4s -- secondary should
    # fire far fewer times than main, proving they're independently paced
    rows, _ = run(tick_rate=0.5, secondary_tick_rate=2.0, duration=4.0,
                   conn=conn, sleep_fn=clock.sleep, clock_fn=clock.monotonic)
    main_count = sum(1 for r in rows if r["command"] == "speed 0 0")
    secondary_count = sum(1 for r in rows if r["command"] == f"current {CURRENT_INSTANCE}")
    assert main_count == 8  # t=0,0.5,...,3.5
    assert secondary_count == 2  # t=0,2


def test_run_reads_final_status_and_errors_after_loop():
    clock = _FakeClock()
    conn = _FakeConn()
    run(tick_rate=10.0, duration=1.0, conn=conn, sleep_fn=clock.sleep, clock_fn=clock.monotonic)
    tail = conn.sent[-3:]
    assert tail == ["status 0", "status 1", f"errors {CURRENT_INSTANCE}"]


def test_run_summary_reports_unchanged_errors_when_nothing_changed():
    clock = _FakeClock()
    conn = _FakeConn()
    _, summary = run(tick_rate=10.0, duration=1.0, conn=conn, sleep_fn=clock.sleep, clock_fn=clock.monotonic)
    assert summary["errors_changed"] is False
    for instance in MOTOR_INSTANCES:
        assert summary["status_delta"][instance] == {"timeout": 0, "checksum": 0, "kickstart": 0}


def test_run_summary_detects_status_counter_increase():
    clock = _FakeClock()
    # Keyed by the exact command "status 0" -- with tick_rate=10.0 >
    # duration=1.0 the main tick still fires once immediately (t=0 always
    # fires), so "status 0" is actually called 3x: baseline, the one
    # mid-loop main-tick read, final. Only baseline-vs-final matters for
    # the delta -- the mid-loop reading in between doesn't feed it.
    conn = _FakeConn(replies={"status 0": [_status_reply(timeout=0), _status_reply(timeout=0),
                                            _status_reply(timeout=5)]})
    _, summary = run(tick_rate=10.0, duration=1.0, conn=conn, sleep_fn=clock.sleep, clock_fn=clock.monotonic)
    assert summary["status_delta"][0]["timeout"] == 5


def test_run_does_not_warn_on_successful_speed_or_reset_replies(caplog):
    # Regression test for the 2026-09-22 false-positive bug: a bare "OK"
    # (speed/reset's real success reply) must not be flagged as a
    # non-zero/unparseable ret.
    clock = _FakeClock()
    conn = _FakeConn()
    with caplog.at_level("WARNING"):
        run(tick_rate=1.0, duration=2.0, conn=conn, sleep_fn=clock.sleep, clock_fn=clock.monotonic)
    assert "non-zero/unparseable ret" not in caplog.text


def test_run_does_not_close_an_externally_provided_conn():
    clock = _FakeClock()
    conn = _FakeConn()
    closed = []
    conn.close = lambda: closed.append(True)
    run(tick_rate=10.0, duration=1.0, conn=conn, sleep_fn=clock.sleep, clock_fn=clock.monotonic)
    assert closed == []


def test_run_honors_a_duration_longer_than_the_module_default():
    # Confirms the schedule actually keeps going past the old hardcoded
    # 60s if duration says so -- regression guard for the --duration flag.
    clock = _FakeClock()
    conn = _FakeConn()
    rows, _ = run(tick_rate=100.0, duration=600.0, conn=conn, sleep_fn=clock.sleep, clock_fn=clock.monotonic)
    assert clock.now == pytest.approx(600.0)
    # tick_rate=100 > 60s means a 60s-capped run would only ever see the
    # single immediate t=0 firing -- a 600s run must see a second one too.
    speed0_count = sum(1 for r in rows if r["command"] == "speed 0 0")
    assert speed0_count == 6  # t=0,100,200,300,400,500


# --- parse_args --------------------------------------------------------

def test_parse_args_duration_defaults_to_module_constant():
    args = parse_args(["--tick-rate", "0.1"])
    assert args.duration == DURATION_S
    assert args.secondary_tick_rate == SECONDARY_TICK_RATE_DEFAULT


def test_parse_args_duration_overridable():
    args = parse_args(["--tick-rate", "0.1", "--duration", "600"])
    assert args.duration == 600.0


def test_parse_args_requires_tick_rate():
    with pytest.raises(SystemExit):
        parse_args(["--duration", "600"])
