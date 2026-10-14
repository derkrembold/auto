import hashlib
import hmac
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_core import Config, Control, ARM, DRIVE, STOP, DISARMED, ARMED, STOPPING, FAULT

KEY = bytes(range(16))


class Clock:
    now = 0.0
    def __call__(self):
        return self.now


@pytest.fixture
def setup():
    clock = Clock()
    control = Control(Config(KEY.hex()), clock)
    nonce = control.challenge("phone")
    control.receive("phone", b"\x00" + hmac.new(KEY, b"auth" + nonce, hashlib.sha256).digest()[:16])
    return control, clock, nonce


def packet(nonce, op, seq, forward=0, steer=0, held=False, limit=100):
    flags = (128 if held else 0) | limit if op == DRIVE else 0
    body = struct.pack("<BIhhB", op, seq, forward, steer, flags)
    return body + hmac.new(KEY, nonce + body, hashlib.sha256).digest()[:10]


def drive(setup):
    control, clock, nonce = setup
    control.receive("phone", packet(nonce, ARM, 1))
    control.receive("phone", packet(nonce, DRIVE, 2, 800, 200, True))
    assert control.tick() == (1200, 720)
    return control, clock, nonce


def test_cannot_drive_without_explicit_start(setup):
    control, _, nonce = setup
    with pytest.raises(ValueError, match="Start"):
        control.receive("phone", packet(nonce, DRIVE, 1, 1000, held=True))
    assert control.tick() == (0, 0)


def test_stop_ramps_both_motors_proportionally_and_latches(setup):
    control, clock, nonce = drive(setup)
    control.receive("phone", packet(nonce, STOP, 3))
    clock.now = .5
    assert control.tick() == (600, 360)
    control.stop()  # repeating stop must not postpone reaching zero
    clock.now = 1.01
    assert control.tick() == (0, 0)
    assert control.state == DISARMED
    with pytest.raises(ValueError):
        control.receive("phone", packet(nonce, DRIVE, 4, 800, held=True))


def test_timeout_stops_without_any_more_client_messages(setup):
    control, clock, _ = drive(setup)
    clock.now = .61
    control.tick()
    assert control.state == STOPPING and control.error == 1
    clock.now = 1.62
    assert control.tick() == (0, 0)


def test_disconnect_ramps_both_and_invalidates_session(setup):
    control, clock, nonce = drive(setup)
    control.disconnect("phone")
    clock.now = 1.1
    assert control.tick() == (0, 0)
    with pytest.raises(ValueError):
        control.receive("phone", packet(nonce, ARM, 3))


def test_release_deadman_stops(setup):
    control, _, nonce = drive(setup)
    control.receive("phone", packet(nonce, DRIVE, 3, 800, held=False))
    assert control.state == STOPPING


def test_replay_or_modified_packet_does_not_refresh_timeout(setup):
    control, clock, nonce = drive(setup)
    clock.now = .5
    with pytest.raises(ValueError):
        control.receive("phone", packet(nonce, DRIVE, 2, 800, held=True))
    bad = bytearray(packet(nonce, DRIVE, 3, 800, held=True)); bad[5] ^= 1
    with pytest.raises(ValueError):
        control.receive("phone", bytes(bad))
    assert control.last_input == 0


def test_only_one_authenticated_controller(setup):
    control, _, _ = setup
    with pytest.raises(ValueError, match="Another"):
        control.challenge("other-phone")
    control.disconnect("other-phone")
    assert control.owner == "phone"


def test_fault_is_latched_and_never_ramps_a_stalled_motor(setup):
    control, _, nonce = drive(setup)
    control.fault()
    assert control.tick() == (0, 0)
    control.stop()
    assert control.state == FAULT
    with pytest.raises(ValueError, match="latched"):
        control.receive("phone", packet(nonce, ARM, 3))


def test_unknown_mapping_cannot_enable_hardware():
    with pytest.raises(ValueError, match="verified"):
        Config(KEY.hex(), live=True)
    with pytest.raises(ValueError):
        Config(KEY.hex(), left=1, right=1)


def test_confirmed_wheel_direction_signs():
    control = Control(Config(KEY.hex(), left_dir='cw', right_dir='ccw'), Clock())
    assert control.mix(500, 0) == (600, -600)
    assert control.mix(-500, 0) == (-600, 600)


def test_speed_limit_also_applies_to_combined_steering(setup):
    control, _, nonce = setup
    control.receive("phone", packet(nonce, ARM, 1))
    control.receive("phone", packet(nonce, DRIVE, 2, 1000, 1000, True, 60))
    assert control.tick() == (720, 0)


def test_invalid_auth_and_expired_challenge():
    clock = Clock(); control = Control(Config(KEY.hex()), clock)
    nonce = control.challenge("phone")
    with pytest.raises(ValueError):
        control.receive("phone", b"\0" * 17)
    clock.now = 31
    with pytest.raises(ValueError):
        control.receive("phone", b"\0" + hmac.new(KEY, b"auth" + nonce, hashlib.sha256).digest()[:16])
    assert control.owner is None


def test_status_fits_minimum_ble_mtu_and_signs_match_golden_vector(setup):
    control, _, _ = setup
    assert len(control.status()) == 20
    values = struct.unpack("<BBBBhhIHH4x", control.status())
    assert values[:4] == (1, 0, 6, 0)  # simulation, authenticated, ready
    fixed_nonce = bytes(range(16, 32))
    assert packet(fixed_nonce, DRIVE, 1, 800, -200, True, 60).hex() == GOLDEN_DRIVE


# Shared with the Dart test. Filled from a separate fixed protocol vector, no random state.
GOLDEN_DRIVE = "0201000000200338ffbcf44a504bf24fee57903f"


def test_bad_auth_attempts_are_limited_across_device_identities():
    clock = Clock()
    control = Control(Config(KEY.hex()), clock)
    for i in range(5):
        peer = 'phone%d' % i
        control.challenge(peer)
        with pytest.raises(ValueError, match='Invalid access code'):
            control.receive(peer, b'\0' * 17)
    nonce = control.challenge('real-phone')
    valid = b'\0' + hmac.new(KEY, b'auth' + nonce, hashlib.sha256).digest()[:16]
    with pytest.raises(ValueError, match='Too many'):
        control.receive('real-phone', valid)
    clock.now = 30
    nonce = control.challenge('real-phone')
    control.receive('real-phone', b'\0' + hmac.new(KEY, b'auth' + nonce, hashlib.sha256).digest()[:16])
    assert control.owner == 'real-phone'
