from unittest.mock import MagicMock, patch

from validate_motor_currentsensor import _invalid_current_reason, run


def test_run_sends_speed_then_checks_for_each_step():
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.recv.return_value = "OK ret=0 val1=0.00 val2=0.00"

    with patch("validate_motor_currentsensor.Client", return_value=fake_conn), \
         patch("validate_motor_currentsensor.time.sleep"):
        run(address="/tmp/fake.sock", speed_sequence=[0, 500],
            checks=["current", "hal"], settle_time=0)

    assert fake_conn.send.call_args_list == [
        (("speed 0",),), (("current",),), (("hal",),),
        (("speed 500",),), (("current",),), (("hal",),),
    ]


def test_run_uses_one_persistent_connection_not_one_shot():
    # A one-shot connection per step would trigger the watchdog's
    # on_disconnect() stop after every step (see
    # raspi/watchdog/CLAUDE.md's Connection Model) — this asserts the
    # Client is only ever opened once for the whole sequence.
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.recv.return_value = "OK ret=0 val1=0.00 val2=0.00"

    with patch("validate_motor_currentsensor.Client", return_value=fake_conn) as fake_client, \
         patch("validate_motor_currentsensor.time.sleep"):
        run(address="/tmp/fake.sock", speed_sequence=[0, 500, 0], settle_time=0)

    fake_client.assert_called_once_with("/tmp/fake.sock", family='AF_UNIX')


def test_run_sleeps_settle_time_after_each_speed_change():
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.recv.return_value = "OK ret=0 val1=0.00 val2=0.00"

    with patch("validate_motor_currentsensor.Client", return_value=fake_conn), \
         patch("validate_motor_currentsensor.time.sleep") as fake_sleep:
        run(address="/tmp/fake.sock", speed_sequence=[500], settle_time=3.0)

    fake_sleep.assert_called_once_with(3.0)


def test_run_defaults_check_order_to_current_hal_rpm():
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.recv.return_value = "OK ret=0 val1=0.00 val2=0.00"

    with patch("validate_motor_currentsensor.Client", return_value=fake_conn), \
         patch("validate_motor_currentsensor.time.sleep"):
        run(address="/tmp/fake.sock", speed_sequence=[0], settle_time=0)

    assert fake_conn.send.call_args_list == [
        (("speed 0",),), (("current",),), (("hal",),), (("rpm",),),
    ]


# --- _invalid_current_reason(): pure logic, no connection needed ---
# Current is bidirectional (ACS712), so negative values are plausible —
# the check is a sanity bound (roughly what the ADC's 0-1023 span maps
# to, see linbus.py's _adc_to_amps()), not a sign check.

def test_valid_current_reply_is_accepted():
    assert _invalid_current_reason("OK ret=0 val1=0.00 val2=-3.50") is None


def test_boundary_values_are_accepted():
    assert _invalid_current_reason("OK ret=0 val1=-25.0 val2=25.0") is None


def test_value_above_plausible_range_is_rejected():
    assert _invalid_current_reason("OK ret=0 val1=30.0 val2=0.0") is not None


def test_value_below_plausible_range_is_rejected():
    assert _invalid_current_reason("OK ret=0 val1=-30.0 val2=0.0") is not None


def test_failed_read_is_rejected():
    assert _invalid_current_reason("OK ret=-5 val1=None val2=None") is not None


def test_unparseable_reply_is_rejected():
    assert _invalid_current_reason("garbage") is not None


# --- run(): aborts and stops the motor on an implausible current reading ---

def test_run_stops_motor_and_aborts_on_out_of_range_current():
    fake_conn = MagicMock()
    fake_conn.__enter__.return_value = fake_conn
    fake_conn.recv.side_effect = [
        "OK",                              # speed 0
        "OK ret=0 val1=100.0 val2=0.0",    # current -- out of range
        "OK",                              # speed 0 (abort stop)
    ]

    with patch("validate_motor_currentsensor.Client", return_value=fake_conn), \
         patch("validate_motor_currentsensor.time.sleep"):
        run(address="/tmp/fake.sock", speed_sequence=[0, 500], settle_time=0)

    assert fake_conn.send.call_args_list == [
        (("speed 0",),), (("current",),), (("speed 0",),),
    ]
