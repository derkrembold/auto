import pytest
from unittest.mock import MagicMock, patch

import capture_step_response
from capture_step_response import (
    run, _soft_stop, _generate_recovery_sequence, _execute_strategy,
    _append_recovery_row, RECOVERY_LOG_FIELDS, STRATEGIES,
    SEQUENCE_MIN_LEN, SEQUENCE_MAX_LEN, SEQUENCE_MAX_BURST, SEQUENCE_MAX_PULSE,
    SEQUENCE_MAX_FULLSPEED, FULLSPEED_STRATEGIES, SEQUENCE_STEP_PAUSE_S,
)


class _FakeClock:
    # Shared state between the mocked time.monotonic()/time.sleep() so
    # sleeping actually advances what monotonic() reports next -- lets
    # run()'s real scheduling logic (target_time vs now, current-sample
    # interval) execute exactly as it would with a real clock, just
    # instantly instead of over real wall-clock seconds.
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _fake_conn(rpm_values, current_values=(), pi_reply="OK",
               status_reply="OK ret=0 timeout=0 checksum=0 kickstart=0 sys_error=0"):
    # Replies based on the command actually sent, not just call order --
    # needed since rpm and current are now interleaved on a different
    # schedule (see run()'s current_sample_interval handling).
    # rpm_values must include one extra value beyond the CSV samples --
    # run() now does one more "rpm" read after the sampling loop, to
    # decide whether the soft-stop ramp should run at all (2026-09-09).
    # Default status_reply's sys_error=0 (MOT_OK) keeps that decision's
    # "no_stall_latched" check true, matching pre-2026-09-09 tests that
    # assume the soft stop always runs.
    conn = MagicMock()
    conn.__enter__.return_value = conn
    rpm_iter = iter(rpm_values)
    current_iter = iter(current_values)
    sent_commands = []

    def fake_send(command):
        sent_commands.append(command)

    def fake_recv():
        command = sent_commands[-1]
        if command == "rpm 0":
            return f"OK ret=0 rpm={next(rpm_iter)} (hex=0x0000)"
        if command == "current 0":
            val1, val2 = next(current_iter)
            return f"OK ret=0 val1={val1} val2={val2}"
        if command.startswith("pi "):
            return pi_reply
        if command == "status 0":
            return status_reply
        return "OK"  # speed 0 <value> / reset 0 / hal 0

    conn.send.side_effect = fake_send
    conn.recv.side_effect = fake_recv
    return conn


def _run_with_fake_clock(conn, **kwargs):
    clock = _FakeClock()
    with patch("capture_step_response.Client", return_value=conn), \
         patch("capture_step_response.logsetup.configure"), \
         patch("capture_step_response.time.sleep", clock.sleep), \
         patch("capture_step_response.time.monotonic", clock.monotonic):
        run(address="/tmp/fake.sock", **kwargs)


def test_run_sends_zero_then_target_speed_first():
    # Third rpm value (600) is the post-loop decision-point read --
    # >= 50% of target_speed=1000, so the soft stop runs (see the new
    # "Decision point" test class below for the skip case).
    conn = _fake_conn([100, 200, 600], [("1.00", "0.50")])
    _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                          duration=0.4)

    sent = [call.args[0] for call in conn.send.call_args_list]
    # "reset 0" + "hal 0" (2026-09-09) are always the first two commands,
    # for a clean firmware baseline + starting rotor position -- see
    # run()'s own comment. Instance 0 = the default `motor` param.
    assert sent[0] == "reset 0"
    assert sent[1] == "hal 0"
    assert sent[2] == "speed 0 0"
    assert sent[3] == "speed 0 1000"
    # Decision point (2026-09-09): hal/rpm/status read again after the
    # sampling loop, then the soft stop (2026-08-20, see _soft_stop()'s
    # own tests below for the exact staging) since rpm/sys_error both
    # look fine.
    assert sent[-8] == "hal 0"
    assert sent[-7] == "rpm 0"
    assert sent[-6] == "status 0"
    assert sent[-5] == "speed 0 800"
    assert sent[-1] == "speed 0 0"


# --- soft stop (added 2026-08-20) ---

def test_soft_stop_stages_speed_down_to_zero():
    conn = _fake_conn([])
    clock = _FakeClock()
    with patch("capture_step_response.time.sleep", clock.sleep):
        _soft_stop(conn, 0, target_speed=1000, steps=5, duration=1.0)

    sent = [call.args[0] for call in conn.send.call_args_list]
    assert sent == ["speed 0 800", "speed 0 600", "speed 0 400", "speed 0 200", "speed 0 0"]


def test_soft_stop_spans_the_requested_duration():
    conn = _fake_conn([])
    clock = _FakeClock()
    with patch("capture_step_response.time.sleep", clock.sleep):
        _soft_stop(conn, 0, target_speed=1000, steps=5, duration=1.0)

    assert clock.now == pytest.approx(1.0)


def test_soft_stop_scales_with_target_speed():
    conn = _fake_conn([])
    clock = _FakeClock()
    with patch("capture_step_response.time.sleep", clock.sleep):
        _soft_stop(conn, 0, target_speed=500, steps=5, duration=1.0)

    sent = [call.args[0] for call in conn.send.call_args_list]
    assert sent == ["speed 0 400", "speed 0 300", "speed 0 200", "speed 0 100", "speed 0 0"]


def test_soft_stop_uses_the_given_motor_instance():
    conn = _fake_conn([])
    clock = _FakeClock()
    with patch("capture_step_response.time.sleep", clock.sleep):
        _soft_stop(conn, 1, target_speed=1000, steps=5, duration=1.0)

    sent = [call.args[0] for call in conn.send.call_args_list]
    assert sent == ["speed 1 800", "speed 1 600", "speed 1 400", "speed 1 200", "speed 1 0"]


def test_run_samples_rpm_expected_number_of_times():
    # 5th value is the post-loop decision-point "rpm" read (2026-09-09)
    # -- not one of the 4 CSV samples this test is actually about.
    conn = _fake_conn([100, 200, 300, 400, 600], [("0.00", "0.00")])
    _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                          duration=0.8)

    rpm_reads = [
        call.args[0] for call in conn.send.call_args_list if call.args[0] == "rpm 0"
    ]
    assert len(rpm_reads) == 5  # 4 CSV samples (0.8s / 0.2s) + 1 decision-point read


def test_run_uses_one_persistent_connection_not_one_shot():
    conn = _fake_conn([100, 600], [("0.00", "0.00")])
    with patch("capture_step_response.Client", return_value=conn) as fake_client, \
         patch("capture_step_response.logsetup.configure"), \
         patch("capture_step_response.time.sleep", _FakeClock().sleep), \
         patch("capture_step_response.time.monotonic", _FakeClock().monotonic):
        run(address="/tmp/fake.sock", target_speed=1000,
            sample_interval=0.2, duration=0.2)

    fake_client.assert_called_once_with("/tmp/fake.sock", family='AF_UNIX')


def test_run_prints_csv_rows(capsys):
    conn = _fake_conn([425, -50, 600], [("1.00", "0.50")])
    _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                          duration=0.4)

    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == "elapsed_ms,rpm,current_val1,current_val2"
    assert lines[1].startswith("0,425,")
    assert lines[2].split(",")[1] == "-50"


# --- current sampled at its own, slower interval ---

def test_current_sampled_only_once_per_current_interval(capsys):
    # sample_interval=0.2, current_sample_interval=1.0 -> current should
    # be read every 5th rpm sample (i=0, i=5, ...), not every row.
    # duration=1.6 (not 1.2) deliberately -- 1.2/0.2 is 5.999... in
    # float64, int() truncates to 5 rows instead of 6; 1.6/0.2 is a
    # clean 8.0. 9th rpm value is the post-loop decision-point read
    # (2026-09-09).
    conn = _fake_conn(
        rpm_values=[0, 1, 2, 3, 4, 5, 6, 7, 600],
        current_values=[("1.00", "0.50"), ("1.20", "0.60")],
    )
    _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                          current_sample_interval=1.0, duration=1.6)

    current_reads = [
        call.args[0] for call in conn.send.call_args_list if call.args[0] == "current 0"
    ]
    assert len(current_reads) == 2  # rows 0 and 5 out of 8 rows


def test_current_columns_blank_when_not_sampled_this_row(capsys):
    conn = _fake_conn(
        rpm_values=[0, 1, 2, 3, 4, 5, 6, 7, 600],
        current_values=[("1.00", "0.50"), ("1.20", "0.60")],
    )
    _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                          current_sample_interval=1.0, duration=1.6)

    lines = capsys.readouterr().out.strip().splitlines()[1:]  # skip header
    assert lines[0] == "0,0,1.00,0.50"       # first row -- current sampled
    assert lines[1] == "200,1,,"             # no current this row
    assert lines[2] == "400,2,,"
    assert lines[3] == "600,3,,"
    assert lines[4] == "800,4,,"
    assert lines[5] == "1000,5,1.20,0.60"    # 1s elapsed -- current sampled again
    assert lines[6] == "1200,6,,"
    assert lines[7] == "1400,7,,"


# --- optional --p-delta/--i-delta (added 2026-08-19) ---

def test_run_sends_pi_first_when_deltas_given():
    conn = _fake_conn([100, 600], [("0.00", "0.00")])
    _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                          duration=0.2, p_delta=0.1, i_delta=-0.05)

    sent = [call.args[0] for call in conn.send.call_args_list]
    assert sent[0] == "reset 0"
    assert sent[1] == "hal 0"
    assert sent[2] == "pi 0 0.1 -0.05"
    assert sent[3] == "speed 0 0"
    assert sent[4] == "speed 0 1000"


def test_run_omits_pi_when_deltas_not_given():
    conn = _fake_conn([100, 600], [("0.00", "0.00")])
    _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                          duration=0.2)

    sent = [call.args[0] for call in conn.send.call_args_list]
    assert sent[0] == "reset 0"
    assert sent[1] == "hal 0"
    assert sent[2] == "speed 0 0"
    assert not any(c.startswith("pi ") for c in sent)


# --- conditional soft-stop ramp (added 2026-09-09) ---
# Found live: on a genuinely stuck rotor (e.g. parked in a Mittelrast),
# the soft stop's own descending nonzero speed commands re-armed
# controlvariableinput and triggered a brand new stuck-detection/
# kickstart cycle -- confirmed via a real "status" showing kickstart=6
# instead of the 3 the stuck-window range alone explains. See run()'s
# own "Decision point" comment.

def test_soft_stop_skipped_when_rpm_below_half_of_target():
    # rpm=50 at the decision point, target_speed=1000 -- well under the
    # 50% (STOP_RAMP_RPM_FRACTION) threshold, so the ramp must not run.
    conn = _fake_conn([0, 50], [("0.00", "0.00")])
    _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                          duration=0.2)

    sent = [call.args[0] for call in conn.send.call_args_list]
    assert "speed 0 800" not in sent  # first soft-stop step never sent
    assert sent[-1] == "speed 0 0"    # still stops, just not via the ramp


def test_soft_stop_skipped_when_stall_tim_err_latched():
    # rpm=900 alone would pass the 50% threshold, but a latched
    # STALL_TIM_ERR (-65) means the firmware itself confirmed it never
    # really got going -- that alone must also skip the ramp.
    conn = _fake_conn(
        [0, 900], [("0.00", "0.00")],
        status_reply="OK ret=0 timeout=0 checksum=0 kickstart=3 sys_error=-65",
    )
    _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                          duration=0.2)

    sent = [call.args[0] for call in conn.send.call_args_list]
    assert "speed 0 800" not in sent
    assert sent[-1] == "speed 0 0"


def test_soft_stop_runs_when_rpm_and_status_both_look_fine():
    conn = _fake_conn([0, 900], [("0.00", "0.00")])
    _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                          duration=0.2)

    sent = [call.args[0] for call in conn.send.call_args_list]
    assert "speed 0 800" in sent  # first soft-stop step did run
    assert sent[-1] == "speed 0 0"


def test_run_aborts_before_speed_when_pi_rejected():
    conn = _fake_conn([100], pi_reply="ERR p_delta out of range (-1.28..1.27)")
    with pytest.raises(SystemExit, match="p_delta out of range"):
        _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                              duration=0.2, p_delta=5.0, i_delta=0.0)

    sent = [call.args[0] for call in conn.send.call_args_list]
    # "reset 0" then "hal 0" always fire first; pi's rejection still
    # aborts before ever reaching speed 0 0 / speed 0 <target>.
    assert sent == ["reset 0", "hal 0", "pi 0 5.0 0.0"]


def test_run_uses_the_given_motor_and_current_instance():
    # Multi-instance sanity check (2026-09-11): every command carries the
    # given motor/current_instance, not the default 0.
    conn = _fake_conn([100, 600], [("0.00", "0.00")])
    _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                          duration=0.2, motor=1, current_instance=1)

    sent = [call.args[0] for call in conn.send.call_args_list]
    assert sent[0] == "reset 1"
    assert sent[1] == "hal 1"
    assert sent[2] == "speed 1 0"
    assert sent[3] == "speed 1 1000"
    assert "rpm 1" in sent
    assert "current 1" in sent
    assert "status 1" in sent


# --- mid-run stall detection + recovery (added 2026-09-09, schema
# reworked 2026-09-10) ---
# STALL_CHECK_DELAY_S=1.0s, RPM_SAMPLE_2_S=1.5s / SAMPLE_INTERVAL=0.2s.
# duration=2.0 -> 10 samples (i=0..9, elapsed 0..1800ms) per attempt --
# long enough that i=5 crosses 1000ms (stall check + rpm_1s) and i=8
# crosses 1500ms (rpm_1p5s). A stalled attempt returns early at i=8.

def _recovery_log_calls(fake_append):
    return [c.args[0] for c in fake_append.call_args_list]


def test_run_recovers_after_confirmed_stall_and_uses_retry_rows(capsys):
    # Attempt 1: rpm=0 throughout -> stall confirmed (sys_error=-65) at
    # i=5, keeps sampling to i=8 for rpm_1p5s, then returns early.
    # Retry (after the sequence): rpm nonzero from i=5 on, so its own
    # stall check never fires and it runs the full window.
    conn = _fake_conn(
        rpm_values=[0] * 14 + [600] * 6,  # 9 (att1) + 10 (retry) + 1 (decision point)
        current_values=[("0.00", "0.00")] * 10,
        status_reply="OK ret=0 timeout=0 checksum=0 kickstart=3 sys_error=-65",
    )
    with patch("capture_step_response._generate_recovery_sequence",
               return_value=["burst_cw", "speed_plus"]), \
         patch("capture_step_response._append_recovery_row") as fake_append:
        _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                              duration=2.0)

    rows = _recovery_log_calls(fake_append)
    assert len(rows) == 2
    seq_row, retry_row = rows
    assert seq_row["phase"] == "sequence"
    assert seq_row["target_speed"] == 1000
    assert seq_row["sequence"] == "burst 0 -500 10 1000 5;speed 0 500;speed 0 0"
    assert seq_row["status_before_sequence"] == "OK ret=0 timeout=0 checksum=0 kickstart=3 sys_error=-65"
    assert seq_row["status_after_sequence"] == "OK ret=0 timeout=0 checksum=0 kickstart=3 sys_error=-65"
    assert retry_row["phase"] == "retry"
    assert retry_row["rpm_1s"] == 600
    assert retry_row["rpm_1p5s"] == 600
    # Full `status` reply captured right after the retry sampling (2026-09-10)
    # -- lets the analysis tool spot a "recovered" retry whose nonzero rpm
    # is really Hall chatter (latched STALL_TIM_ERR despite rpm != 0).
    assert retry_row["status_after_retry"] == "OK ret=0 timeout=0 checksum=0 kickstart=3 sys_error=-65"
    # Both rows share the same join key.
    assert seq_row["timestamp"] == retry_row["timestamp"]

    lines = capsys.readouterr().out.strip().splitlines()
    rpm_column = [line.split(",")[1] for line in lines[1:]]  # skip header
    # Only the retry's 10 rows are printed, not the failed first attempt's.
    assert rpm_column == ["0"] * 5 + ["600"] * 5

    sent = [call.args[0] for call in conn.send.call_args_list]
    assert "burst 0 -500 10 1000 5" in sent  # burst_cw's exact recipe
    assert "speed 0 500" in sent
    assert sent.count("reset 0") == 2  # initial + before the retry


def test_run_aborts_after_stall_persists_through_retry():
    # Both attempts stall (rpm=0 throughout). Still writes both recovery
    # rows (the "retry" one shows rpm_1s/rpm_1p5s = 0), then aborts.
    conn = _fake_conn(
        rpm_values=[0] * 18,  # 9 (att1) + 9 (retry, early return) -- no decision point
        current_values=[("0.00", "0.00")] * 10,
        status_reply="OK ret=0 timeout=0 checksum=0 kickstart=3 sys_error=-65",
    )
    with patch("capture_step_response._generate_recovery_sequence",
               return_value=["pulse_plus", "pulse_minus"]), \
         patch("capture_step_response._append_recovery_row") as fake_append:
        with pytest.raises(SystemExit, match="stall persisted"):
            _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                                  duration=2.0)

    rows = _recovery_log_calls(fake_append)
    assert len(rows) == 2
    assert rows[0]["phase"] == "sequence"
    assert rows[1]["phase"] == "retry"
    assert rows[1]["rpm_1s"] == 0
    assert rows[1]["rpm_1p5s"] == 0
    assert rows[1]["status_after_retry"] == "OK ret=0 timeout=0 checksum=0 kickstart=3 sys_error=-65"

    sent = [call.args[0] for call in conn.send.call_args_list]
    # Exactly one recovery sequence ran (not a second one after the
    # retry also stalled).
    assert sent.count("pulse 0 1000") == 1
    assert sent.count("pulse 0 -1000") == 1


# --- recovery sequence generation (_generate_recovery_sequence) ---

def test_generate_recovery_sequence_respects_all_constraints():
    rng_seeds = range(200)
    import random as random_module
    for seed in rng_seeds:
        sequence = _generate_recovery_sequence(rng=random_module.Random(seed))

        assert SEQUENCE_MIN_LEN <= len(sequence) <= SEQUENCE_MAX_LEN
        assert all(name in STRATEGIES for name in sequence)

        burst_count = sum(1 for name in sequence if STRATEGIES[name]["kind"] == "burst")
        pulse_count = sum(1 for name in sequence if STRATEGIES[name]["kind"] == "pulse")
        fullspeed_count = sum(1 for name in sequence if name in FULLSPEED_STRATEGIES)
        assert burst_count <= SEQUENCE_MAX_BURST
        assert pulse_count <= SEQUENCE_MAX_PULSE
        # speed_max_plus + speed_max_minus COMBINED -- forward-then-reverse
        # at full power is the shape closest to the 2026-09-08 MOSFET failure.
        assert fullspeed_count <= SEQUENCE_MAX_FULLSPEED

        for a, b in zip(sequence, sequence[1:]):
            assert a != b  # never the same strategy twice in a row


def test_generate_recovery_sequence_still_reaches_full_speed_strategies():
    # The SEQUENCE_MAX_FULLSPEED cap must limit, not exclude -- over
    # enough seeds both speed_max_plus and speed_max_minus should still
    # turn up somewhere.
    import random as random_module
    seen = set()
    for seed in range(200):
        seen.update(_generate_recovery_sequence(rng=random_module.Random(seed)))
    assert "speed_max_plus" in seen
    assert "speed_max_minus" in seen


def test_execute_strategy_full_speed_emits_speed_target_then_zero():
    for name, value in (("speed_max_plus", 1000), ("speed_max_minus", -1000)):
        conn = MagicMock()
        clock = _FakeClock()
        with patch("capture_step_response.time.sleep", clock.sleep):
            commands = _execute_strategy(conn, name, 0)
        assert commands == [f"speed 0 {value}", "speed 0 0"]


def test_execute_strategy_includes_the_given_motor_instance():
    conn = MagicMock()
    clock = _FakeClock()
    with patch("capture_step_response.time.sleep", clock.sleep):
        commands = _execute_strategy(conn, "speed_max_plus", 1)
    assert commands == ["speed 1 1000", "speed 1 0"]


def test_execute_strategy_pauses_at_least_step_pause_after_every_kind():
    # Every kind (speed/pulse/burst) must leave at least
    # SEQUENCE_STEP_PAUSE_S of (simulated) elapsed time behind it, so
    # back-to-back _execute_strategy() calls in a sequence never run
    # closer together than that -- the electronics-stress reason
    # discussed with the user (2026-09-09).
    for name in STRATEGIES:
        conn = MagicMock()
        clock = _FakeClock()
        with patch("capture_step_response.time.sleep", clock.sleep):
            _execute_strategy(conn, name, 0)
        assert clock.now >= SEQUENCE_STEP_PAUSE_S, (
            f"{name} only paused {clock.now}s, expected >= {SEQUENCE_STEP_PAUSE_S}s")


def test_execute_strategy_sequence_never_runs_closer_than_step_pause():
    # A realistic multi-step sequence -- every step-to-step gap (the
    # time between one strategy's last send-then-sleep and the next
    # one's first send) must be >= SEQUENCE_STEP_PAUSE_S.
    conn = MagicMock()
    clock = _FakeClock()
    sequence = ["burst_cw", "speed_plus", "pulse_minus"]
    with patch("capture_step_response.time.sleep", clock.sleep):
        checkpoints = []
        for name in sequence:
            _execute_strategy(conn, name, 0)
            checkpoints.append(clock.now)

    gaps = [b - a for a, b in zip(checkpoints, checkpoints[1:])]
    # float accumulation over several time.sleep() calls can land a
    # hair under the exact target (e.g. 0.09999999999999998) -- a
    # tiny tolerance avoids failing on that, not on a real gap.
    assert all(gap >= SEQUENCE_STEP_PAUSE_S - 1e-9 for gap in gaps), gaps


# --- recovery-log appends (_append_recovery_row, added 2026-09-09,
# schema reworked 2026-09-10) ---
# Uses tmp_path (a real pytest-managed temp directory) instead of the
# real repo -- RECOVERY_LOG_PATH is a plain relative filename, so it's
# redirected via monkeypatch + chdir rather than ever touching the
# actual recovery_sequences.csv in the repo root.

def test_append_recovery_row_writes_header_only_on_first_call(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(capture_step_response, "RECOVERY_LOG_PATH", "recovery_sequences.csv")

    _append_recovery_row({
        "timestamp": "2026-09-10T12:00:00.000001", "phase": "sequence",
        "target_speed": 1000,
        "hal_before_sequence": "OK data=['0x00', '0x01', '0x00']",
        "status_before_sequence": "OK ret=0 sys_error=-65",
        "sequence": "burst 0 -500 10 1000 5;speed 0 500;speed 0 0",
        "hal_after_sequence": "OK data=['0x00', '0x00', '0x01']",
        "status_after_sequence": "OK ret=0 sys_error=-65",
    })
    _append_recovery_row({
        "timestamp": "2026-09-10T12:00:00.000001", "phase": "retry",
        "rpm_1s": 600, "rpm_1p5s": 625,
        "status_after_retry": "OK ret=0 timeout=0 checksum=0 kickstart=3 sys_error=0",
    })

    import csv as _csv
    with open(tmp_path / "recovery_sequences.csv", newline="") as f:
        parsed = list(_csv.DictReader(f))
    assert len(parsed) == 2  # header once, one row per call
    assert parsed[0]["phase"] == "sequence"
    assert parsed[0]["sequence"] == "burst 0 -500 10 1000 5;speed 0 500;speed 0 0"
    assert parsed[0]["hal_before_sequence"] == "OK data=['0x00', '0x01', '0x00']"
    assert parsed[0]["rpm_1s"] == ""  # blank in a "sequence" row
    assert parsed[0]["status_after_retry"] == ""  # blank in a "sequence" row
    assert parsed[1]["phase"] == "retry"
    assert parsed[1]["rpm_1s"] == "600"
    assert parsed[1]["status_after_retry"] == "OK ret=0 timeout=0 checksum=0 kickstart=3 sys_error=0"
    assert parsed[1]["timestamp"] == parsed[0]["timestamp"]  # join key
    assert parsed[1]["sequence"] == ""  # blank in a "retry" row


def test_append_recovery_row_appends_not_truncates(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(capture_step_response, "RECOVERY_LOG_PATH", "recovery_sequences.csv")

    for _ in range(5):
        _append_recovery_row({"timestamp": "t", "phase": "retry", "rpm_1s": 600, "rpm_1p5s": 625})

    content = (tmp_path / "recovery_sequences.csv").read_text().strip().splitlines()
    assert len(content) == 1 + 5  # header once, one row per call, nothing overwritten
    assert content[0] == ",".join(RECOVERY_LOG_FIELDS)
