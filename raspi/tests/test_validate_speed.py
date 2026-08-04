from unittest.mock import MagicMock, patch

from validate_speed import run


def test_run_sends_speed_then_rpm_for_each_step():
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.recv.return_value = "OK"

    with patch("validate_speed.Client", return_value=fake_conn), \
         patch("validate_speed.time.sleep"):
        run(address="/tmp/fake.sock", sequence=[0, 400, -400], settle_time=0)

    assert fake_conn.send.call_args_list == [
        (("speed 0",),), (("rpm",),),
        (("speed 400",),), (("rpm",),),
        (("speed -400",),), (("rpm",),),
    ]


def test_run_uses_one_persistent_connection_not_one_shot():
    # A one-shot connection per step would trigger the watchdog's
    # on_disconnect() stop after every step (see
    # raspi/watchdog/CLAUDE.md's Connection Model) — this asserts the
    # Client is only ever opened once for the whole sequence.
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.recv.return_value = "OK"

    with patch("validate_speed.Client", return_value=fake_conn) as fake_client, \
         patch("validate_speed.time.sleep"):
        run(address="/tmp/fake.sock", sequence=[0, 400, 0], settle_time=0)

    fake_client.assert_called_once_with("/tmp/fake.sock", family='AF_UNIX')


def test_run_sleeps_settle_time_between_speed_and_rpm():
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.recv.return_value = "OK"

    with patch("validate_speed.Client", return_value=fake_conn), \
         patch("validate_speed.time.sleep") as fake_sleep:
        run(address="/tmp/fake.sock", sequence=[400], settle_time=3.0)

    fake_sleep.assert_called_once_with(3.0)
