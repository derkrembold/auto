from unittest.mock import MagicMock, patch

from motorcontrol import send_command, main


def test_send_command_sends_and_returns_reply():
    fake_conn = MagicMock()
    fake_conn.recv.return_value = "OK"
    fake_conn.__enter__.return_value = fake_conn

    with patch("motorcontrol.Client", return_value=fake_conn) as fake_client:
        reply = send_command("speed 300", address="/tmp/fake.sock")

    fake_client.assert_called_once_with("/tmp/fake.sock", family='AF_UNIX')
    fake_conn.send.assert_called_once_with("speed 300")
    assert reply == "OK"


def _run_interactive(inputs):
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.recv.return_value = "OK"

    with patch("motorcontrol.Client", return_value=fake_conn), \
         patch("builtins.input", side_effect=inputs):
        main()

    return fake_conn


def test_interactive_sends_each_typed_command():
    fake_conn = _run_interactive(["speed 600", "rpm", "exit"])
    assert fake_conn.send.call_args_list == [
        (("speed 600",),), (("rpm",),),
    ]


def test_interactive_ignores_blank_lines():
    fake_conn = _run_interactive(["", "hal", "exit"])
    fake_conn.send.assert_called_once_with("hal")


def test_interactive_stops_on_ctrl_c():
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    with patch("motorcontrol.Client", return_value=fake_conn), \
         patch("builtins.input", side_effect=KeyboardInterrupt):
        main()  # must not raise
    fake_conn.send.assert_not_called()


def test_help_is_handled_locally_not_sent_to_watchdog():
    fake_conn = _run_interactive(["help", "exit"])
    fake_conn.send.assert_not_called()
