from unittest.mock import MagicMock, patch

from capture_step_response import run


def _fake_conn(rpm_values):
    # First two recv() calls answer the "speed 0" / "speed <target>"
    # setup commands, then one rpm reply per sample, then one more for
    # the final "speed 0".
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.recv.side_effect = (
        ["OK", "OK"]
        + [f"OK ret=0 rpm={v} (hex=0x0000)" for v in rpm_values]
        + ["OK"]
    )
    return conn


def test_run_sends_zero_then_target_speed_first():
    conn = _fake_conn([100, 200])
    with patch("capture_step_response.Client", return_value=conn), \
         patch("capture_step_response.time.sleep"), \
         patch("capture_step_response.time.monotonic", side_effect=iter(range(100))):
        run(address="/tmp/fake.sock", target_speed=1000,
            sample_interval=0.2, duration=0.4)

    sent = [call.args[0] for call in conn.send.call_args_list]
    assert sent[0] == "speed 0"
    assert sent[1] == "speed 1000"
    assert sent[-1] == "speed 0"


def test_run_samples_expected_number_of_times():
    conn = _fake_conn([100, 200, 300, 400])
    with patch("capture_step_response.Client", return_value=conn), \
         patch("capture_step_response.time.sleep"), \
         patch("capture_step_response.time.monotonic", side_effect=iter(range(100))):
        run(address="/tmp/fake.sock", target_speed=1000,
            sample_interval=0.2, duration=0.8)

    rpm_reads = sent = [
        call.args[0] for call in conn.send.call_args_list if call.args[0] == "rpm"
    ]
    assert len(rpm_reads) == 4  # 0.8s / 0.2s


def test_run_uses_one_persistent_connection_not_one_shot():
    conn = _fake_conn([100])
    with patch("capture_step_response.Client", return_value=conn) as fake_client, \
         patch("capture_step_response.time.sleep"), \
         patch("capture_step_response.time.monotonic", side_effect=iter(range(100))):
        run(address="/tmp/fake.sock", target_speed=1000,
            sample_interval=0.2, duration=0.2)

    fake_client.assert_called_once_with("/tmp/fake.sock", family='AF_UNIX')


def test_run_prints_csv_rows(capsys):
    conn = _fake_conn([425, -50])
    with patch("capture_step_response.Client", return_value=conn), \
         patch("capture_step_response.time.sleep"), \
         patch("capture_step_response.time.monotonic", side_effect=iter(range(100))):
        run(address="/tmp/fake.sock", target_speed=1000,
            sample_interval=0.2, duration=0.4)

    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == "elapsed_ms,rpm"
    assert lines[1].endswith(",425")
    assert lines[2].endswith(",-50")
