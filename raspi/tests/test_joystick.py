import random
from unittest.mock import patch

import pytest

from joystick import (
    _clamp, _apply_deadzone, _compute_speeds, _value_changed, _is_confirmed, _ramp_down_both,
    _read_rpm, _is_stalled, _generate_gentle_sequence, _run_gentle_sequence, _handle_recovery_button,
    parse_args, DIRECTION_SIGN, RAMP_STEPS, RAMP_DURATION,
    GENTLE_STRATEGIES, SEQUENCE_MIN_LEN, SEQUENCE_MAX_LEN, SEQUENCE_MAX_PULSE,
    VERIFY_SPEED, STALL_TIM_ERR,
)


class _FakeSender:
    def __init__(self):
        self.calls = []  # list of (instance, value) -- send_speed() only

    def send_speed(self, instance, value):
        self.calls.append((instance, value))
        return "SIMULATED"


def _status_reply(sys_error=0):
    return f"OK ret=0 timeout=0 checksum=0 kickstart=0 sys_error={sys_error}"


class _FakeRecoverySender:
    """Replies keyed by exact command first, falling back to the verb,
    falling back to a stable healthy-looking default -- same pattern as
    validate_lin_stress.py's _FakeConn. self.commands records every
    command (both send() and send_speed()) in order, for asserting call
    sequence/content."""

    def __init__(self, replies=None):
        self.commands = []
        self.replies = replies or {}

    def send(self, command):
        self.commands.append(command)
        verb = command.split()[0]
        for key in (command, verb):
            if key in self.replies:
                value = self.replies[key]
                if isinstance(value, list):
                    return value.pop(0) if len(value) > 1 else value[0]
                return value
        if verb in ("speed", "reset", "pulse"):
            return "OK"
        if verb == "rpm":
            return "OK ret=0 rpm=0 (hex=0x0000)"
        if verb == "status":
            return _status_reply()
        if verb == "hal":
            return "OK ret=0 data=['0x01', '0x00', '0x01']"
        raise AssertionError(f"unexpected command: {command}")

    def send_speed(self, instance, value):
        return self.send(f"speed {instance} {value}")


REQUIRED_ARGS = ["--left", "0", "--right", "1", "--left-dir", "cw", "--right-dir", "ccw"]


# --- _clamp / _apply_deadzone -------------------------------------------

def test_clamp_within_range_unchanged():
    assert _clamp(0.3, -1.0, 1.0) == 0.3


def test_clamp_above_max_saturates():
    assert _clamp(1.5, -1.0, 1.0) == 1.0


def test_clamp_below_min_saturates():
    assert _clamp(-1.5, -1.0, 1.0) == -1.0


def test_deadzone_zeroes_small_value():
    assert _apply_deadzone(200, 500) == 0


def test_deadzone_keeps_value_at_or_above_threshold():
    assert _apply_deadzone(500, 500) == 500
    assert _apply_deadzone(-700, 500) == -700


# --- _compute_speeds ------------------------------------------------------

def test_compute_speeds_straight_forward_both_equal():
    # forward=1.0, steer=0.0 -> both wheels get the same full-forward speed
    left, right = _compute_speeds(1.0, 0.0, max_rpm=1200, deadzone=0, left_sign=1, right_sign=1)
    assert left == 1200
    assert right == 1200


def test_compute_speeds_pure_steer_in_place():
    # forward=0.0, steer=1.0 -> left forward, right backward (turn in place)
    left, right = _compute_speeds(0.0, 1.0, max_rpm=1200, deadzone=0, left_sign=1, right_sign=1)
    assert left == 1200
    assert right == -1200


def test_compute_speeds_clamped_when_forward_and_steer_combine_past_max():
    left, right = _compute_speeds(1.0, 1.0, max_rpm=1200, deadzone=0, left_sign=1, right_sign=1)
    assert left == 1200  # clamped, not 2400
    assert right == 0


def test_compute_speeds_applies_deadzone_after_scaling():
    # small forward value scaled by max_rpm still lands under the deadzone
    left, right = _compute_speeds(0.1, 0.0, max_rpm=1200, deadzone=500, left_sign=1, right_sign=1)
    assert left == 0
    assert right == 0


def test_compute_speeds_ccw_direction_flips_sign():
    left, right = _compute_speeds(1.0, 0.0, max_rpm=1200, deadzone=0,
                                   left_sign=DIRECTION_SIGN["cw"], right_sign=DIRECTION_SIGN["ccw"])
    assert left == 1200
    assert right == -1200


# --- _value_changed ---------------------------------------------------------

def test_value_changed_false_for_identical_values():
    assert _value_changed(500, 500) is False


def test_value_changed_true_for_any_difference_with_zero_threshold():
    assert _value_changed(500, 501) is True
    assert _value_changed(500, 499) is True


def test_value_changed_false_within_threshold():
    # LT-style comparison -- small float jitter under the threshold doesn't count
    assert _value_changed(0.0, 0.03, threshold=0.05) is False


def test_value_changed_true_beyond_threshold():
    assert _value_changed(0.0, 0.06, threshold=0.05) is True


def test_value_changed_true_at_exact_threshold_boundary_is_false():
    # strictly greater-than, matching a real change needing to clear the margin
    assert _value_changed(0.0, 0.05, threshold=0.05) is False


# --- _is_confirmed ---------------------------------------------------------

def test_is_confirmed_false_before_first_press():
    assert _is_confirmed(None, now=100.0, timeout=10.0) is False


def test_is_confirmed_true_within_window():
    assert _is_confirmed(last_confirm_time=100.0, now=105.0, timeout=10.0) is True


def test_is_confirmed_false_exactly_at_boundary_plus_epsilon():
    assert _is_confirmed(last_confirm_time=100.0, now=110.01, timeout=10.0) is False


def test_is_confirmed_true_at_exact_boundary():
    assert _is_confirmed(last_confirm_time=100.0, now=110.0, timeout=10.0) is True


# --- _ramp_down_both --------------------------------------------------------

def test_ramp_down_both_ends_at_zero_for_both_motors():
    sender = _FakeSender()
    sleeps = []
    _ramp_down_both(sender, left_instance=0, right_instance=1,
                     left_speed=1000, right_speed=-1000,
                     sleep_fn=lambda s: sleeps.append(s))
    left_calls = [v for (inst, v) in sender.calls if inst == 0]
    right_calls = [v for (inst, v) in sender.calls if inst == 1]
    assert left_calls[-1] == 0
    assert right_calls[-1] == 0
    assert len(left_calls) == RAMP_STEPS
    assert len(right_calls) == RAMP_STEPS


def test_ramp_down_both_is_monotonically_descending_in_magnitude():
    sender = _FakeSender()
    _ramp_down_both(sender, left_instance=0, right_instance=1,
                     left_speed=1000, right_speed=0,
                     sleep_fn=lambda s: None)
    left_calls = [v for (inst, v) in sender.calls if inst == 0]
    assert left_calls == sorted(left_calls, reverse=True)
    assert left_calls[0] < 1000  # first step is already below the starting speed


def test_ramp_down_both_interleaves_left_and_right_per_step():
    sender = _FakeSender()
    _ramp_down_both(sender, left_instance=0, right_instance=1,
                     left_speed=500, right_speed=500,
                     sleep_fn=lambda s: None)
    instances_in_order = [inst for (inst, v) in sender.calls]
    # left then right, repeated -- not all of left's sends followed by all of right's
    assert instances_in_order[:2] == [0, 1]


def test_ramp_down_both_sleeps_step_interval_each_step():
    sender = _FakeSender()
    sleeps = []
    _ramp_down_both(sender, left_instance=0, right_instance=1,
                     left_speed=1000, right_speed=1000,
                     sleep_fn=lambda s: sleeps.append(s))
    assert len(sleeps) == RAMP_STEPS
    assert sleeps[0] == pytest.approx(RAMP_DURATION / RAMP_STEPS)


# --- parse_args fail-fast checks -------------------------------------------

def test_parse_args_accepts_valid_required_args():
    args = parse_args(REQUIRED_ARGS)
    assert args.left == 0
    assert args.right == 1
    assert args.left_dir == "cw"
    assert args.right_dir == "ccw"
    assert args.live is False  # simulate is the default


def test_parse_args_rejects_same_left_right_instance():
    with pytest.raises(SystemExit):
        parse_args(["--left", "0", "--right", "0", "--left-dir", "cw", "--right-dir", "cw"])


def test_parse_args_rejects_out_of_range_instance():
    with pytest.raises(SystemExit):
        parse_args(["--left", "0", "--right", "9", "--left-dir", "cw", "--right-dir", "cw"])


def test_parse_args_rejects_duplicated_left_flag():
    with pytest.raises(SystemExit):
        parse_args(["--left", "0", "--left", "1", "--right", "2", "--left-dir", "cw", "--right-dir", "cw"])


def test_parse_args_rejects_duplicated_left_dir_flag():
    with pytest.raises(SystemExit):
        parse_args(["--left", "0", "--right", "1", "--left-dir", "cw", "--left-dir", "ccw", "--right-dir", "cw"])


def test_parse_args_rejects_invalid_direction_value():
    with pytest.raises(SystemExit):
        parse_args(["--left", "0", "--right", "1", "--left-dir", "sideways", "--right-dir", "cw"])


def test_parse_args_requires_all_four_mandatory_flags():
    with pytest.raises(SystemExit):
        parse_args(["--left", "0", "--right", "1", "--left-dir", "cw"])  # missing --right-dir


def test_parse_args_live_flag_opts_in():
    args = parse_args(REQUIRED_ARGS + ["--live"])
    assert args.live is True


def test_parse_args_defaults_match_documented_values():
    args = parse_args(REQUIRED_ARGS)
    assert args.max_rpm == 1200
    assert args.deadzone == 500
    assert args.confirm_timeout == 10.0
    assert args.poll_interval == 0.2
    assert args.axis_forward == 4
    assert args.axis_steer == 3
    assert args.axis_lt == 2
    assert args.lt_change_threshold == 0.05
    assert args.recovery_button == 1


# --- _read_rpm / _is_stalled ------------------------------------------

def test_read_rpm_parses_value():
    sender = _FakeRecoverySender(replies={"rpm 0": "OK ret=0 rpm=450 (hex=0x01c2)"})
    assert _read_rpm(sender, 0) == 450


def test_read_rpm_returns_none_on_unparseable_reply():
    sender = _FakeRecoverySender(replies={"rpm 0": "ERR timeout"})
    assert _read_rpm(sender, 0) is None


def test_is_stalled_true_on_latched_stall_tim_err():
    sender = _FakeRecoverySender(replies={"status 0": _status_reply(sys_error=STALL_TIM_ERR)})
    assert _is_stalled(sender, 0) is True


def test_is_stalled_false_when_healthy():
    sender = _FakeRecoverySender(replies={"status 0": _status_reply(sys_error=0)})
    assert _is_stalled(sender, 0) is False


def test_is_stalled_false_on_unparseable_reply():
    sender = _FakeRecoverySender(replies={"status 0": "ERR timeout"})
    assert _is_stalled(sender, 0) is False


# --- _generate_gentle_sequence -----------------------------------------

def test_generate_gentle_sequence_length_within_bounds():
    for _ in range(20):
        sequence = _generate_gentle_sequence(rng=random.Random())
        assert SEQUENCE_MIN_LEN <= len(sequence) <= SEQUENCE_MAX_LEN


def test_generate_gentle_sequence_only_known_strategies():
    sequence = _generate_gentle_sequence(rng=random.Random(1))
    assert all(name in GENTLE_STRATEGIES for name in sequence)


def test_generate_gentle_sequence_no_immediate_repeat():
    for seed in range(30):
        sequence = _generate_gentle_sequence(rng=random.Random(seed))
        assert all(sequence[i] != sequence[i + 1] for i in range(len(sequence) - 1))


def test_generate_gentle_sequence_respects_pulse_cap():
    for seed in range(30):
        sequence = _generate_gentle_sequence(rng=random.Random(seed))
        pulse_count = sum(1 for name in sequence if GENTLE_STRATEGIES[name]["kind"] == "pulse")
        assert pulse_count <= SEQUENCE_MAX_PULSE


def test_generate_gentle_sequence_excludes_fullpower_strategies():
    # GENTLE_STRATEGIES itself must never contain the aggressive ones --
    # a structural guarantee, not just a runtime behavior.
    assert "speed_max_plus" not in GENTLE_STRATEGIES
    assert "speed_max_minus" not in GENTLE_STRATEGIES
    assert "burst_cw" not in GENTLE_STRATEGIES
    assert "burst_ccw" not in GENTLE_STRATEGIES


# --- _run_gentle_sequence -----------------------------------------------

def test_run_gentle_sequence_speed_strategy_sends_value_then_zero():
    sender = _FakeRecoverySender()
    sleeps = []
    sequence, commands = _run_gentle_sequence(
        sender, motor=0, sleep_fn=lambda s: sleeps.append(s), rng=random.Random(2))
    for name in sequence:
        strategy = GENTLE_STRATEGIES[name]
        if strategy["kind"] == "speed":
            assert f"speed 0 {strategy['value']}" in commands
            assert "speed 0 0" in commands


def test_run_gentle_sequence_pulse_strategy_sends_single_command():
    sender = _FakeRecoverySender()
    sequence, commands = _run_gentle_sequence(
        sender, motor=1, sleep_fn=lambda s: None, rng=random.Random(3))
    for name in sequence:
        strategy = GENTLE_STRATEGIES[name]
        if strategy["kind"] == "pulse":
            assert f"pulse 1 {strategy['value']}" in commands


def test_run_gentle_sequence_returns_sequence_matching_commands_sent():
    sender = _FakeRecoverySender()
    sequence, commands = _run_gentle_sequence(
        sender, motor=0, sleep_fn=lambda s: None, rng=random.Random(4))
    assert commands == sender.commands


# --- _handle_recovery_button --------------------------------------------

def test_handle_recovery_button_noop_when_neither_stalled():
    sender = _FakeRecoverySender()  # default status replies are healthy
    with patch("joystick._append_recovery_row") as fake_append:
        handled = _handle_recovery_button(sender, 0, 1, sleep_fn=lambda s: None, rng=random.Random(5))
    assert handled is False
    assert sender.commands == ["status 0", "status 1"]
    fake_append.assert_not_called()


def test_handle_recovery_button_left_stalled_resets_and_sequences_only_left():
    sender = _FakeRecoverySender(replies={
        "status 0": _status_reply(sys_error=STALL_TIM_ERR),
        "status 1": _status_reply(sys_error=0),
    })
    with patch("joystick._append_recovery_row"):
        handled = _handle_recovery_button(sender, 0, 1, sleep_fn=lambda s: None, rng=random.Random(6))
    assert handled is True
    assert "reset 0" in sender.commands
    assert "reset 1" not in sender.commands


def test_handle_recovery_button_both_stalled_resets_and_sequences_both_in_order():
    sender = _FakeRecoverySender(replies={
        "status 0": _status_reply(sys_error=STALL_TIM_ERR),
        "status 1": _status_reply(sys_error=STALL_TIM_ERR),
    })
    with patch("joystick._append_recovery_row"):
        handled = _handle_recovery_button(sender, 0, 1, sleep_fn=lambda s: None, rng=random.Random(7))
    assert handled is True
    assert "reset 0" in sender.commands
    assert "reset 1" in sender.commands
    # motor 0's whole sequence (reset through status_after) completes
    # before motor 1's begins -- sequential, not simultaneous.
    assert sender.commands.index("reset 0") < sender.commands.index("reset 1")


def test_handle_recovery_button_runs_joint_verification_step_on_both_motors():
    sender = _FakeRecoverySender(replies={
        "status 0": _status_reply(sys_error=STALL_TIM_ERR),
        "status 1": _status_reply(sys_error=0),
    })
    with patch("joystick._append_recovery_row"):
        _handle_recovery_button(sender, 0, 1, sleep_fn=lambda s: None, rng=random.Random(8))
    assert f"speed 0 {VERIFY_SPEED}" in sender.commands
    assert f"speed 1 {VERIFY_SPEED}" in sender.commands
    # ends with both motors explicitly back at 0
    assert sender.commands[-2:] == ["speed 0 0", "speed 1 0"]


def test_handle_recovery_button_ends_with_a_ramp_down_not_an_abrupt_stop():
    # Regression test: an earlier version sent speed 0 directly after
    # the verification step, matching the harsh-stop issue found live
    # for capture_step_response.py (2026-08-20) -- must ramp instead.
    sender = _FakeRecoverySender(replies={
        "status 0": _status_reply(sys_error=STALL_TIM_ERR),
        "status 1": _status_reply(sys_error=0),
    })
    with patch("joystick._append_recovery_row"):
        _handle_recovery_button(sender, 0, 1, sleep_fn=lambda s: None, rng=random.Random(11))
    # the ramp's own intermediate step (800*4/5=640) must appear for
    # both motors between the VERIFY_SPEED command and the final 0s
    assert "speed 0 640" in sender.commands
    assert "speed 1 640" in sender.commands
    speed_800_index = sender.commands.index(f"speed 0 {VERIFY_SPEED}")
    speed_640_index = sender.commands.index("speed 0 640")
    final_zero_index = len(sender.commands) - 2
    assert speed_800_index < speed_640_index < final_zero_index


def test_handle_recovery_button_logs_sequence_row_per_stalled_motor_and_one_retry_row():
    sender = _FakeRecoverySender(replies={
        "status 0": _status_reply(sys_error=STALL_TIM_ERR),
        "status 1": _status_reply(sys_error=STALL_TIM_ERR),
    })
    with patch("joystick._append_recovery_row") as fake_append:
        _handle_recovery_button(sender, 0, 1, sleep_fn=lambda s: None, rng=random.Random(9))
    phases = [call.args[0]["phase"] for call in fake_append.call_args_list]
    assert phases == ["sequence", "sequence", "retry"]
    assert all(call.args[0]["source"] == "joystick" for call in fake_append.call_args_list)


def test_handle_recovery_button_retry_row_has_motor_instance_both():
    sender = _FakeRecoverySender(replies={
        "status 0": _status_reply(sys_error=STALL_TIM_ERR),
        "status 1": _status_reply(sys_error=0),
    })
    with patch("joystick._append_recovery_row") as fake_append:
        _handle_recovery_button(sender, 0, 1, sleep_fn=lambda s: None, rng=random.Random(10))
    retry_rows = [call.args[0] for call in fake_append.call_args_list if call.args[0]["phase"] == "retry"]
    assert len(retry_rows) == 1
    assert retry_rows[0]["motor_instance"] == "both"
