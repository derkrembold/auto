import random
from unittest.mock import patch

import pytest

from joystick import (
    _clamp, _apply_deadzone, _compute_speeds, _value_changed, _is_confirmed, _ramp_down_both,
    _read_rpm, _is_stalled, _generate_gentle_sequence, _run_gentle_sequence, _handle_recovery_button,
    _new_kickstart_tracker, _update_kickstart_tracker, _read_status_fields, _poll_stall_feedback,
    _open_rumble_device,
    parse_args, DIRECTION_SIGN, RAMP_STEPS, RAMP_DURATION,
    GENTLE_STRATEGIES, SEQUENCE_MIN_LEN, SEQUENCE_MAX_LEN, SEQUENCE_MAX_PULSE,
    VERIFY_SPEED, STALL_TIM_ERR, STALL_WARN_THRESHOLD,
)


class _FakeSender:
    def __init__(self):
        self.calls = []  # list of (instance, value) -- send_speed() only

    def send_speed(self, instance, value):
        self.calls.append((instance, value))
        return "SIMULATED"


def _status_reply(sys_error=0, kickstart=0):
    return f"OK ret=0 timeout=0 checksum=0 kickstart={kickstart} sys_error={sys_error}"


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


# --- _update_kickstart_tracker (Issue #22) --------------------------------

def test_kickstart_tracker_first_reading_sets_baseline_no_warn():
    tracker = _new_kickstart_tracker()
    warned = _update_kickstart_tracker(tracker, rpm=0, kickstart_count=5)
    assert warned is False
    assert tracker["prev_kickstart"] == 5
    assert tracker["accum"] == 0


def test_kickstart_tracker_accumulates_delta_across_stuck_polls():
    # Plain accumulation, well below threshold -- threshold-agnostic
    # (doesn't hardcode STALL_WARN_THRESHOLD's actual value, see the
    # next test for why that matters: a real live-testing session
    # 2026-10-02 lowered it from 3 to 2, and a hardcoded version of
    # this test broke silently at that point).
    tracker = _new_kickstart_tracker()
    _update_kickstart_tracker(tracker, rpm=0, kickstart_count=10)  # baseline
    warned = _update_kickstart_tracker(tracker, rpm=0, kickstart_count=11)  # +1
    assert warned is False
    assert tracker["accum"] == 1


def test_kickstart_tracker_warns_exactly_once_at_threshold():
    tracker = _new_kickstart_tracker()
    tracker["prev_kickstart"] = 0
    tracker["accum"] = STALL_WARN_THRESHOLD - 1
    warned_at_threshold = _update_kickstart_tracker(tracker, rpm=0, kickstart_count=1)  # +1 -> crosses threshold
    assert warned_at_threshold is True
    assert tracker["accum"] == STALL_WARN_THRESHOLD
    warned_again = _update_kickstart_tracker(tracker, rpm=0, kickstart_count=2)
    assert warned_again is False  # already warned this episode -- no re-fire every tick


def test_kickstart_tracker_resets_accum_and_warned_on_rpm_nonzero():
    tracker = _new_kickstart_tracker()
    for count in (0, 1, 2, 3):
        _update_kickstart_tracker(tracker, rpm=0, kickstart_count=count)  # reaches warned=True, accum=3
    _update_kickstart_tracker(tracker, rpm=400, kickstart_count=3)  # motor confirmed turning again
    assert tracker["accum"] == 0
    assert tracker["warned"] is False
    assert tracker["prev_kickstart"] == 3


def test_kickstart_tracker_handles_mod_256_wraparound():
    tracker = _new_kickstart_tracker()
    _update_kickstart_tracker(tracker, rpm=0, kickstart_count=254)  # baseline
    _update_kickstart_tracker(tracker, rpm=0, kickstart_count=255)  # +1, accum=1
    warned = _update_kickstart_tracker(tracker, rpm=0, kickstart_count=1)  # wraps: 1-255+256=2, accum=3
    assert tracker["accum"] == 3
    assert warned is True


def test_kickstart_tracker_skips_update_on_unparseable_status():
    tracker = _new_kickstart_tracker()
    _update_kickstart_tracker(tracker, rpm=0, kickstart_count=5)
    warned = _update_kickstart_tracker(tracker, rpm=0, kickstart_count=None)
    assert warned is False
    assert tracker["prev_kickstart"] == 5  # unchanged, not poisoned by a failed read
    assert tracker["accum"] == 0


def test_kickstart_tracker_rpm_none_is_not_treated_as_confirmed_running():
    # Codex I-0022 finding #3: `rpm != 0` was also True for rpm=None (a
    # failed/unparseable read), silently wiping a real in-progress
    # episode. rpm=None must fall through to the same stuck-
    # accumulation path as rpm=0, not the confirmed-running reset.
    tracker = _new_kickstart_tracker()
    tracker["prev_kickstart"] = 0
    tracker["accum"] = STALL_WARN_THRESHOLD - 1
    warned = _update_kickstart_tracker(tracker, rpm=None, kickstart_count=1)
    assert warned is True  # the delta from the still-valid kickstart_count wasn't lost
    assert tracker["accum"] == STALL_WARN_THRESHOLD


def test_kickstart_tracker_rpm_none_and_kickstart_none_leaves_episode_untouched():
    tracker = _new_kickstart_tracker()
    tracker["prev_kickstart"] = 0
    tracker["accum"] = 1
    warned = _update_kickstart_tracker(tracker, rpm=None, kickstart_count=None)
    assert warned is False
    assert tracker["accum"] == 1  # untouched, not reset and not accumulated


# --- _read_status_fields (Issue #22) --------------------------------------

def test_read_status_fields_parses_both_values():
    sender = _FakeRecoverySender(replies={"status 0": _status_reply(sys_error=STALL_TIM_ERR, kickstart=4)})
    sys_error, kickstart_count = _read_status_fields(sender, 0)
    assert sys_error == STALL_TIM_ERR
    assert kickstart_count == 4


def test_read_status_fields_none_on_unparseable_reply():
    sender = _FakeRecoverySender(replies={"status 0": "GARBAGE"})
    sys_error, kickstart_count = _read_status_fields(sender, 0)
    assert sys_error is None
    assert kickstart_count is None


# --- _poll_stall_feedback (Issue #22) --------------------------------------
# Checks both motors every call -- real 200ms-per-motor sampling, the
# Autor's final decision (2026-10-02, after an intermediate single-
# motor-per-call version was tried and reverted, see _poll_stall_
# feedback()'s own docstring for the full back-and-forth).

def _ack_long(pending_long_trackers):
    # Mirrors exactly what run() does after successfully firing the
    # rumble (not what _poll_stall_feedback does -- it deliberately
    # does NOT set this itself, see its docstring). Tests call this to
    # simulate "the effect actually played," distinct from a tick where
    # firing was suppressed (e.g. still busy) and this is skipped.
    for tracker in pending_long_trackers:
        tracker["long_fired"] = True


def test_poll_stall_feedback_returns_none_when_healthy():
    sender = _FakeRecoverySender(replies={
        "rpm 0": "OK ret=0 rpm=400 (hex=0x0190)",
        "rpm 1": "OK ret=0 rpm=400 (hex=0x0190)",
    })
    left_tracker, right_tracker = _new_kickstart_tracker(), _new_kickstart_tracker()
    trigger, pending = _poll_stall_feedback(sender, 0, 1, left_tracker, right_tracker)
    assert trigger is None
    assert pending == []


def test_poll_stall_feedback_returns_long_on_confirmed_stall():
    sender = _FakeRecoverySender(replies={
        "rpm 0": "OK ret=0 rpm=0 (hex=0x0000)",
        "status 0": _status_reply(sys_error=STALL_TIM_ERR),
        "rpm 1": "OK ret=0 rpm=400 (hex=0x0190)",
    })
    left_tracker, right_tracker = _new_kickstart_tracker(), _new_kickstart_tracker()
    trigger, pending = _poll_stall_feedback(sender, 0, 1, left_tracker, right_tracker)
    assert trigger == "long"
    assert pending == [left_tracker]


def test_poll_stall_feedback_long_fires_only_once_while_stall_stays_latched():
    # Real bug found live 2026-10-02 (a genuine Mittelrast stall): with
    # no "already fired" gating at all, sys_error staying latched
    # (nothing resets it automatically) made this return "long" on
    # every call, which run() turned into a near-continuous rumble
    # instead of one alert. Same fix shape as "warned" already had for
    # the short one -- but see the NEXT test for a second bug this
    # first fix introduced.
    sender = _FakeRecoverySender(replies={
        "rpm 0": "OK ret=0 rpm=0 (hex=0x0000)",
        "status 0": _status_reply(sys_error=STALL_TIM_ERR),
        "rpm 1": "OK ret=0 rpm=400 (hex=0x0190)",
    })
    left_tracker, right_tracker = _new_kickstart_tracker(), _new_kickstart_tracker()
    trigger, pending = _poll_stall_feedback(sender, 0, 1, left_tracker, right_tracker)
    assert trigger == "long"
    _ack_long(pending)  # simulates run() successfully firing it
    assert _poll_stall_feedback(sender, 0, 1, left_tracker, right_tracker)[0] is None
    assert _poll_stall_feedback(sender, 0, 1, left_tracker, right_tracker)[0] is None


def test_poll_stall_feedback_long_retries_if_not_acknowledged():
    # Second real bug, found live the SAME session as the fix above:
    # the first version set tracker["long_fired"] the moment the stall
    # was merely OBSERVED, not once the rumble actually played. If that
    # first observation landed while a short rumble was still
    # busy-playing (run() suppresses firing in that case), the long
    # alert was marked "already fired" regardless -- and then silently
    # never retried for the rest of that stall episode, confirmed in
    # joystick.log (a real stall with sys_error=-65 latched for 2.9s+
    # produced zero "confirmed stall" log lines). Fixed by splitting
    # detection (here) from acknowledgment (the caller, only on actual
    # successful playback) -- simulated here by simply NOT calling
    # _ack_long() between polls.
    sender = _FakeRecoverySender(replies={
        "rpm 0": "OK ret=0 rpm=0 (hex=0x0000)",
        "status 0": _status_reply(sys_error=STALL_TIM_ERR),
        "rpm 1": "OK ret=0 rpm=400 (hex=0x0190)",
    })
    left_tracker, right_tracker = _new_kickstart_tracker(), _new_kickstart_tracker()
    trigger1, pending1 = _poll_stall_feedback(sender, 0, 1, left_tracker, right_tracker)
    assert trigger1 == "long"
    # Not acknowledged (as if run() found the rumble still busy) --
    # the next poll must still offer "long" again, not silently drop it.
    trigger2, pending2 = _poll_stall_feedback(sender, 0, 1, left_tracker, right_tracker)
    assert trigger2 == "long"
    assert pending2 == [left_tracker]


def test_poll_stall_feedback_long_fires_again_after_stall_clears_and_relatches():
    sender = _FakeRecoverySender(replies={
        "rpm 0": ["OK ret=0 rpm=0 (hex=0x0000)", "OK ret=0 rpm=400 (hex=0x0190)",
                  "OK ret=0 rpm=0 (hex=0x0000)"],
        "status 0": [_status_reply(sys_error=STALL_TIM_ERR), _status_reply(sys_error=0),
                     _status_reply(sys_error=STALL_TIM_ERR)],
        "rpm 1": "OK ret=0 rpm=400 (hex=0x0190)",
    })
    left_tracker, right_tracker = _new_kickstart_tracker(), _new_kickstart_tracker()
    trigger, pending = _poll_stall_feedback(sender, 0, 1, left_tracker, right_tracker)
    assert trigger == "long"
    _ack_long(pending)
    assert _poll_stall_feedback(sender, 0, 1, left_tracker, right_tracker)[0] is None  # reset, motor running again
    assert _poll_stall_feedback(sender, 0, 1, left_tracker, right_tracker)[0] == "long"  # a genuinely new episode


def test_poll_stall_feedback_right_motor_alone_can_trigger_long():
    sender = _FakeRecoverySender(replies={
        "rpm 0": "OK ret=0 rpm=400 (hex=0x0190)",
        "rpm 1": "OK ret=0 rpm=0 (hex=0x0000)",
        "status 1": _status_reply(sys_error=STALL_TIM_ERR),
    })
    left_tracker, right_tracker = _new_kickstart_tracker(), _new_kickstart_tracker()
    trigger, pending = _poll_stall_feedback(sender, 0, 1, left_tracker, right_tracker)
    assert trigger == "long"
    assert pending == [right_tracker]


def test_poll_stall_feedback_returns_short_on_warn_threshold_crossing():
    sender = _FakeRecoverySender(replies={
        "rpm 0": "OK ret=0 rpm=0 (hex=0x0000)",
        "status 0": _status_reply(kickstart=1),  # prev=0 -> delta=1, accum 2+1=3
        "rpm 1": "OK ret=0 rpm=400 (hex=0x0190)",
    })
    left_tracker, right_tracker = _new_kickstart_tracker(), _new_kickstart_tracker()
    left_tracker["prev_kickstart"] = 0
    left_tracker["accum"] = STALL_WARN_THRESHOLD - 1
    trigger, pending = _poll_stall_feedback(sender, 0, 1, left_tracker, right_tracker)
    assert trigger == "short"
    assert pending == []


def test_poll_stall_feedback_long_takes_priority_over_short_across_motors():
    # Confirms the cross-motor priority Codex's I-0022 follow-up review
    # found missing in the intermediate alternating version -- a
    # confirmed stall on one motor must win even if the OTHER motor is
    # the one crossing its own warn threshold in the same poll.
    sender = _FakeRecoverySender(replies={
        "rpm 0": "OK ret=0 rpm=0 (hex=0x0000)",
        "status 0": _status_reply(sys_error=STALL_TIM_ERR, kickstart=1),
        "rpm 1": "OK ret=0 rpm=0 (hex=0x0000)",
        "status 1": _status_reply(kickstart=1),
    })
    left_tracker, right_tracker = _new_kickstart_tracker(), _new_kickstart_tracker()
    left_tracker["prev_kickstart"] = 0
    left_tracker["accum"] = STALL_WARN_THRESHOLD - 1
    right_tracker["prev_kickstart"] = 0
    right_tracker["accum"] = STALL_WARN_THRESHOLD - 1
    assert _poll_stall_feedback(sender, 0, 1, left_tracker, right_tracker)[0] == "long"


def test_poll_stall_feedback_long_takes_priority_over_short_across_motors_mirrored():
    # Mirror of the above with left/right swapped -- Codex's I-0022
    # third-pass review (2026-10-02) suggested this as a follow-up so
    # the priority check isn't only exercised with the left motor as
    # the confirmed-stalled one.
    sender = _FakeRecoverySender(replies={
        "rpm 0": "OK ret=0 rpm=0 (hex=0x0000)",
        "status 0": _status_reply(kickstart=1),
        "rpm 1": "OK ret=0 rpm=0 (hex=0x0000)",
        "status 1": _status_reply(sys_error=STALL_TIM_ERR, kickstart=1),
    })
    left_tracker, right_tracker = _new_kickstart_tracker(), _new_kickstart_tracker()
    left_tracker["prev_kickstart"] = 0
    left_tracker["accum"] = STALL_WARN_THRESHOLD - 1
    right_tracker["prev_kickstart"] = 0
    right_tracker["accum"] = STALL_WARN_THRESHOLD - 1
    assert _poll_stall_feedback(sender, 0, 1, left_tracker, right_tracker)[0] == "long"


# --- _open_rumble_device (Issue #22) -- Codex I-0022 finding #5 ------------
# Device enumeration/open/capabilities must degrade gracefully, not raise,
# regardless of what's actually installed in the environment running these
# tests -- evdev/evdev_ecodes are explicitly patched in every case below
# rather than relying on this dev machine's own "evdev not installed" state.

class _FakeEcodes:
    EV_FF = 0x50
    FF_RUMBLE = 0x50


class _FakeEvdevDevice:
    def __init__(self, path, name="Logitech Gamepad F710", has_ff=True, caps_exc=None):
        self.path = path
        self.name = name
        self._has_ff = has_ff
        self._caps_exc = caps_exc
        self.closed = False

    def capabilities(self, verbose=False):
        if self._caps_exc is not None:
            raise self._caps_exc
        return {_FakeEcodes.EV_FF: []} if self._has_ff else {}

    def close(self):
        self.closed = True


class _FakeEvdevModule:
    """`entries` maps a device path to either a _FakeEvdevDevice (open
    succeeds) or an Exception instance (InputDevice() raises it)."""

    def __init__(self, entries, list_devices_exc=None):
        self.entries = entries
        self._list_devices_exc = list_devices_exc

    def list_devices(self):
        if self._list_devices_exc is not None:
            raise self._list_devices_exc
        return list(self.entries.keys())

    def InputDevice(self, path):
        entry = self.entries[path]
        if isinstance(entry, Exception):
            raise entry
        return entry


def test_open_rumble_device_none_when_evdev_unavailable():
    with patch("joystick.evdev", None):
        assert _open_rumble_device("Logitech Gamepad F710") is None


def test_open_rumble_device_none_when_list_devices_fails():
    fake_evdev = _FakeEvdevModule({}, list_devices_exc=OSError("no /dev/input"))
    with patch("joystick.evdev", fake_evdev), patch("joystick.evdev_ecodes", _FakeEcodes):
        assert _open_rumble_device("Logitech Gamepad F710") is None


def test_open_rumble_device_skips_device_that_disappears_on_open():
    good = _FakeEvdevDevice("/dev/input/event3")
    fake_evdev = _FakeEvdevModule({
        "/dev/input/event2": OSError("device vanished"),
        "/dev/input/event3": good,
    })
    with patch("joystick.evdev", fake_evdev), patch("joystick.evdev_ecodes", _FakeEcodes), \
            patch("joystick.evdev_ff") as fake_ff:
        fake_ff.Effect.return_value = object()
        good.upload_effect = lambda effect: 0
        result = _open_rumble_device("Logitech Gamepad F710")
    assert result is not None
    device, short_id, long_id = result
    assert device is good


def test_open_rumble_device_closes_and_skips_device_with_failing_capabilities():
    broken = _FakeEvdevDevice("/dev/input/event2", caps_exc=OSError("capability read failed"))
    good = _FakeEvdevDevice("/dev/input/event3")
    fake_evdev = _FakeEvdevModule({
        "/dev/input/event2": broken,
        "/dev/input/event3": good,
    })
    with patch("joystick.evdev", fake_evdev), patch("joystick.evdev_ecodes", _FakeEcodes), \
            patch("joystick.evdev_ff") as fake_ff:
        fake_ff.Effect.return_value = object()
        good.upload_effect = lambda effect: 0
        result = _open_rumble_device("Logitech Gamepad F710")
    assert broken.closed is True
    assert result is not None
    assert result[0] is good


def test_open_rumble_device_none_when_no_unique_match():
    dev_a = _FakeEvdevDevice("/dev/input/event2", name="Other Controller")
    dev_b = _FakeEvdevDevice("/dev/input/event3", name="Other Controller")
    fake_evdev = _FakeEvdevModule({"/dev/input/event2": dev_a, "/dev/input/event3": dev_b})
    with patch("joystick.evdev", fake_evdev), patch("joystick.evdev_ecodes", _FakeEcodes):
        assert _open_rumble_device("Logitech Gamepad F710") is None


def test_open_rumble_device_none_when_effect_upload_fails():
    dev = _FakeEvdevDevice("/dev/input/event2")
    dev.upload_effect = lambda effect: (_ for _ in ()).throw(OSError("upload failed"))
    fake_evdev = _FakeEvdevModule({"/dev/input/event2": dev})
    with patch("joystick.evdev", fake_evdev), patch("joystick.evdev_ecodes", _FakeEcodes), \
            patch("joystick.evdev_ff") as fake_ff:
        fake_ff.Effect.return_value = object()
        result = _open_rumble_device("Logitech Gamepad F710")
    assert result is None
    assert dev.closed is True
