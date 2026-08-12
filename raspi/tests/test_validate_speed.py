from unittest.mock import MagicMock, patch

from validate_speed import run


def _fake_conn(rpm_values, current_values=()):
    # Replies based on the command actually sent, not just call order —
    # same pattern as test_capture_step_response.py, needed since
    # "speed", "rpm", and "current" are now interleaved.
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
        return "OK"  # speed <value>

    conn.send.side_effect = fake_send
    conn.recv.side_effect = fake_recv
    return conn


def test_run_sends_speed_then_rpm_then_current_for_each_step():
    conn = _fake_conn([0, 400, -400], [("0.00", "0.00")] * 3)
    with patch("validate_speed.Client", return_value=conn), \
         patch("validate_speed.logsetup.configure"), \
         patch("validate_speed.time.sleep"):
        run(address="/tmp/fake.sock", sequence=[0, 400, -400], settle_time=0)

    assert conn.send.call_args_list == [
        (("speed 0",),), (("rpm",),), (("current",),),
        (("speed 400",),), (("rpm",),), (("current",),),
        (("speed -400",),), (("rpm",),), (("current",),),
    ]


def test_run_uses_one_persistent_connection_not_one_shot():
    # A one-shot connection per step would trigger the watchdog's
    # on_disconnect() stop after every step (see
    # raspi/watchdog/CLAUDE.md's Connection Model) — this asserts the
    # Client is only ever opened once for the whole sequence.
    conn = _fake_conn([0, 400, 0], [("0.00", "0.00")] * 3)
    with patch("validate_speed.Client", return_value=conn) as fake_client, \
         patch("validate_speed.logsetup.configure"), \
         patch("validate_speed.time.sleep"):
        run(address="/tmp/fake.sock", sequence=[0, 400, 0], settle_time=0)

    fake_client.assert_called_once_with("/tmp/fake.sock", family='AF_UNIX')


def test_run_sleeps_settle_time_between_speed_and_rpm():
    conn = _fake_conn([400], [("0.00", "0.00")])
    with patch("validate_speed.Client", return_value=conn), \
         patch("validate_speed.logsetup.configure"), \
         patch("validate_speed.time.sleep") as fake_sleep:
        run(address="/tmp/fake.sock", sequence=[400], settle_time=3.0)

    fake_sleep.assert_called_once_with(3.0)


def test_run_prints_csv_header_and_rows(capsys):
    conn = _fake_conn([400, -400], [("1.20", "1.10"), ("-1.30", "-1.25")])
    with patch("validate_speed.Client", return_value=conn), \
         patch("validate_speed.logsetup.configure"), \
         patch("validate_speed.time.sleep"):
        run(address="/tmp/fake.sock", sequence=[400, -400], settle_time=0)

    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == "elapsed_ms,speed,rpm,current_val1,current_val2"
    assert lines[1].split(",")[1:] == ["400", "400", "1.20", "1.10"]
    assert lines[2].split(",")[1:] == ["-400", "-400", "-1.30", "-1.25"]
