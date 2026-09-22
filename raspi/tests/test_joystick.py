import pytest

from joystick import (
    _clamp, _apply_deadzone, _compute_speeds, _value_changed, _is_confirmed, _ramp_down_both,
    parse_args, DIRECTION_SIGN, RAMP_STEPS, RAMP_DURATION,
)


class _FakeSender:
    def __init__(self):
        self.calls = []  # list of (instance, value)

    def send_speed(self, instance, value):
        self.calls.append((instance, value))
        return "SIMULATED"


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
