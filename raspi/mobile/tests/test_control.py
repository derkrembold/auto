import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_core import Config, Control, CLAIM, ARM, DRIVE, STOP, DISARMED, ARMED, STOPPING, FAULT


class Clock:
    now = 0.0
    def __call__(self):
        return self.now


@pytest.fixture
def setup():
    clock = Clock()
    control = Control(Config(), clock)
    control.connect("phone")
    control.receive("phone", bytes([CLAIM]))
    return control, clock


def packet(op, seq, forward=0, steer=0, held=False, limit=100):
    flags = (128 if held else 0) | limit if op == DRIVE else 0
    return struct.pack("<BIhhB", op, seq, forward, steer, flags)


def drive(setup):
    control, clock = setup
    control.receive("phone", packet(ARM, 1))
    control.receive("phone", packet(DRIVE, 2, 800, 200, True))
    assert control.tick() == (1200, 720)
    return control, clock


def test_cannot_drive_without_explicit_start(setup):
    control, _ = setup
    with pytest.raises(ValueError, match="Start"):
        control.receive("phone", packet(DRIVE, 1, 1000, held=True))
    assert control.tick() == (0, 0)


def test_stop_ramps_both_motors_proportionally_and_latches(setup):
    control, clock = drive(setup)
    control.receive("phone", packet(STOP, 3))
    clock.now = .5
    assert control.tick() == (600, 360)
    control.stop()  # repeating stop must not postpone reaching zero
    clock.now = 1.01
    assert control.tick() == (0, 0)
    assert control.state == DISARMED
    with pytest.raises(ValueError):
        control.receive("phone", packet(DRIVE, 4, 800, held=True))


def test_timeout_stops_without_any_more_client_messages(setup):
    control, clock = drive(setup)
    clock.now = .61
    control.tick()
    assert control.state == STOPPING and control.error == 1
    clock.now = 1.62
    assert control.tick() == (0, 0)


def test_disconnect_ramps_both_and_invalidates_session(setup):
    control, clock = drive(setup)
    control.disconnect("phone")
    clock.now = 1.1
    assert control.tick() == (0, 0)
    with pytest.raises(ValueError):
        control.receive("phone", packet(ARM, 3))


def test_release_deadman_stops(setup):
    control, _ = drive(setup)
    control.receive("phone", packet(DRIVE, 3, 800, held=False))
    assert control.state == STOPPING


def test_replayed_or_malformed_packet_does_not_refresh_timeout(setup):
    control, clock = drive(setup)
    clock.now = .5
    with pytest.raises(ValueError):
        control.receive("phone", packet(DRIVE, 2, 800, held=True))
    with pytest.raises(ValueError):
        control.receive("phone", packet(DRIVE, 3, 800, held=True) + b"\0")
    assert control.last_input == 0


def test_only_one_controlling_phone(setup):
    control, _ = setup
    with pytest.raises(ValueError, match="Another"):
        control.connect("other-phone")
    control.disconnect("other-phone")
    assert control.owner == "phone"


def test_observer_cannot_command_or_claim_twice():
    control = Control(Config(), Clock())
    with pytest.raises(ValueError, match="Not connected"):
        control.receive("stranger", bytes([CLAIM]))
    control.connect("phone")
    with pytest.raises(ValueError, match="Claim control first"):
        control.receive("phone", packet(ARM, 1))
    control.receive("phone", bytes([CLAIM]))
    with pytest.raises(ValueError, match="already claimed"):
        control.receive("phone", bytes([CLAIM]))


def test_fault_is_latched_and_never_ramps_a_stalled_motor(setup):
    control, _ = drive(setup)
    control.fault()
    assert control.tick() == (0, 0)
    control.stop()
    assert control.state == FAULT
    with pytest.raises(ValueError, match="latched"):
        control.receive("phone", packet(ARM, 3))


def test_unknown_mapping_cannot_enable_hardware():
    with pytest.raises(ValueError, match="verified"):
        Config(live=True)
    with pytest.raises(ValueError):
        Config(left=1, right=1)


def test_confirmed_wheel_direction_signs():
    control = Control(Config(left_dir='cw', right_dir='ccw'), Clock())
    assert control.mix(500, 0) == (600, -600)
    assert control.mix(-500, 0) == (-600, 600)


def test_speed_limit_also_applies_to_combined_steering(setup):
    control, _ = setup
    control.receive("phone", packet(ARM, 1))
    control.receive("phone", packet(DRIVE, 2, 1000, 1000, True, 60))
    assert control.tick() == (720, 0)


def test_status_is_20_bytes_version_2_and_drive_matches_golden_vector(setup):
    control, _ = setup
    assert len(control.status()) == 20
    values = struct.unpack("<BBBBhhIHH4x", control.status())
    assert values[:4] == (2, 0, 6, 0)  # version 2; simulation, claimed, ready
    assert packet(DRIVE, 1, 800, -200, True, 60).hex() == GOLDEN_DRIVE


# Shared with the Dart test.
GOLDEN_DRIVE = "0201000000200338ffbc"
