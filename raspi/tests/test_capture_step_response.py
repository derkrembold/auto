import pytest
from unittest.mock import MagicMock, patch

from capture_step_response import run, _soft_stop


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


def _fake_conn(rpm_values, current_values=(), pi_reply="OK"):
    # Replies based on the command actually sent, not just call order --
    # needed since rpm and current are now interleaved on a different
    # schedule (see run()'s current_sample_interval handling).
    conn = MagicMock()
    conn.__enter__.return_value = conn
    rpm_iter = iter(rpm_values)
    current_iter = iter(current_values)
    sent_commands = []

    def fake_send(command):
        sent_commands.append(command)

    def fake_recv():
        command = sent_commands[-1]
        if command == "rpm":
            return f"OK ret=0 rpm={next(rpm_iter)} (hex=0x0000)"
        if command == "current":
            val1, val2 = next(current_iter)
            return f"OK ret=0 val1={val1} val2={val2}"
        if command.startswith("pi "):
            return pi_reply
        return "OK"  # speed 0 / speed <target>

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
    conn = _fake_conn([100, 200], [("1.00", "0.50")])
    _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                          duration=0.4)

    sent = [call.args[0] for call in conn.send.call_args_list]
    assert sent[0] == "speed 0"
    assert sent[1] == "speed 1000"
    # Staged soft stop (2026-08-20), not a single abrupt "speed 0" --
    # see _soft_stop()'s own tests below for the exact staging.
    assert sent[-1] == "speed 0"
    assert sent[-2] != "speed 0"


# --- soft stop (added 2026-08-20) ---

def test_soft_stop_stages_speed_down_to_zero():
    conn = _fake_conn([])
    clock = _FakeClock()
    with patch("capture_step_response.time.sleep", clock.sleep):
        _soft_stop(conn, target_speed=1000, steps=5, duration=1.0)

    sent = [call.args[0] for call in conn.send.call_args_list]
    assert sent == ["speed 800", "speed 600", "speed 400", "speed 200", "speed 0"]


def test_soft_stop_spans_the_requested_duration():
    conn = _fake_conn([])
    clock = _FakeClock()
    with patch("capture_step_response.time.sleep", clock.sleep):
        _soft_stop(conn, target_speed=1000, steps=5, duration=1.0)

    assert clock.now == pytest.approx(1.0)


def test_soft_stop_scales_with_target_speed():
    conn = _fake_conn([])
    clock = _FakeClock()
    with patch("capture_step_response.time.sleep", clock.sleep):
        _soft_stop(conn, target_speed=500, steps=5, duration=1.0)

    sent = [call.args[0] for call in conn.send.call_args_list]
    assert sent == ["speed 400", "speed 300", "speed 200", "speed 100", "speed 0"]


def test_run_samples_rpm_expected_number_of_times():
    conn = _fake_conn([100, 200, 300, 400], [("0.00", "0.00")])
    _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                          duration=0.8)

    rpm_reads = [
        call.args[0] for call in conn.send.call_args_list if call.args[0] == "rpm"
    ]
    assert len(rpm_reads) == 4  # 0.8s / 0.2s


def test_run_uses_one_persistent_connection_not_one_shot():
    conn = _fake_conn([100], [("0.00", "0.00")])
    with patch("capture_step_response.Client", return_value=conn) as fake_client, \
         patch("capture_step_response.logsetup.configure"), \
         patch("capture_step_response.time.sleep", _FakeClock().sleep), \
         patch("capture_step_response.time.monotonic", _FakeClock().monotonic):
        run(address="/tmp/fake.sock", target_speed=1000,
            sample_interval=0.2, duration=0.2)

    fake_client.assert_called_once_with("/tmp/fake.sock", family='AF_UNIX')


def test_run_prints_csv_rows(capsys):
    conn = _fake_conn([425, -50], [("1.00", "0.50")])
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
    # clean 8.0.
    conn = _fake_conn(
        rpm_values=[0, 1, 2, 3, 4, 5, 6, 7],
        current_values=[("1.00", "0.50"), ("1.20", "0.60")],
    )
    _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                          current_sample_interval=1.0, duration=1.6)

    current_reads = [
        call.args[0] for call in conn.send.call_args_list if call.args[0] == "current"
    ]
    assert len(current_reads) == 2  # rows 0 and 5 out of 8 rows


def test_current_columns_blank_when_not_sampled_this_row(capsys):
    conn = _fake_conn(
        rpm_values=[0, 1, 2, 3, 4, 5, 6, 7],
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
    conn = _fake_conn([100], [("0.00", "0.00")])
    _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                          duration=0.2, p_delta=0.1, i_delta=-0.05)

    sent = [call.args[0] for call in conn.send.call_args_list]
    assert sent[0] == "pi 0.1 -0.05"
    assert sent[1] == "speed 0"
    assert sent[2] == "speed 1000"


def test_run_omits_pi_when_deltas_not_given():
    conn = _fake_conn([100], [("0.00", "0.00")])
    _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                          duration=0.2)

    sent = [call.args[0] for call in conn.send.call_args_list]
    assert sent[0] == "speed 0"
    assert not any(c.startswith("pi ") for c in sent)


def test_run_aborts_before_speed_when_pi_rejected():
    conn = _fake_conn([100], pi_reply="ERR p_delta out of range (-1.28..1.27)")
    with pytest.raises(SystemExit, match="p_delta out of range"):
        _run_with_fake_clock(conn, target_speed=1000, sample_interval=0.2,
                              duration=0.2, p_delta=5.0, i_delta=0.0)

    sent = [call.args[0] for call in conn.send.call_args_list]
    assert sent == ["pi 5.0 0.0"]  # never reached speed 0 / speed <target>
