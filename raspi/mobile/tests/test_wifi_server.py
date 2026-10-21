"""WLAN transport over a real loopback socket, simulation only (no watchdog socket)."""
import socket
import struct
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_core import Config, Control, ARM, DRIVE, ARMED, STOPPING, DISARMED
from network_policy import allowed, parse_networks
from wifi_server import Server


def start(networks=None):
    control = Control(Config(), time.monotonic)
    lock, done = threading.Lock(), threading.Event()
    instance = Server(control, lock, "127.0.0.1", 0, networks=networks)

    def loop():
        while not done.is_set():
            instance.poll(0.02)
            with lock:
                control.tick()

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()

    def stop():
        done.set()
        thread.join(timeout=2)
        instance.close()
    return instance, control, stop


@pytest.fixture
def server():
    instance, control, stop = start()
    yield instance, control
    stop()


class Client:
    def __init__(self, address):
        self.sock = socket.create_connection(address, timeout=2)
        self.buffer = b""

    def frame(self):
        while not (self.buffer and len(self.buffer) > self.buffer[0]):
            data = self.sock.recv(1024)
            if not data:
                raise ConnectionError("closed")
            self.buffer += data
        size = self.buffer[0]
        payload, self.buffer = self.buffer[1:1 + size], self.buffer[1 + size:]
        return payload[:1], payload[1:]

    def until(self, kind, predicate=lambda payload: True):
        for _ in range(100):
            got, payload = self.frame()
            if got == kind and predicate(payload):
                return payload
        raise AssertionError("expected frame not received")

    def send(self, packet):
        self.sock.sendall(bytes([len(packet)]) + packet)


def command(op, seq, forward=0, steer=0, flags=0):
    return struct.pack("<BIhhB", op, seq, forward, steer, flags)


def claim(client):
    kind, status = client.frame()
    assert kind == b"S" and status[0] == 2 and not status[2] & 2
    client.send(b"\x00")
    client.until(b"S", lambda status: status[2] & 2)


def test_claimed_drive_is_acknowledged_by_sequence(server):
    instance, control = server
    client = Client(instance.address)
    claim(client)
    client.send(command(ARM, 1))
    status = client.until(b"S", lambda s: struct.unpack_from("<I", s, 8)[0] == 1)
    assert status[1] == ARMED
    client.send(command(DRIVE, 2, forward=1000, flags=128 | 100))
    status = client.until(b"S", lambda s: struct.unpack_from("<I", s, 8)[0] == 2)
    assert control.target == (1200, 1200)
    client.sock.close()


def test_command_before_claim_gets_reason_and_no_session(server):
    instance, control = server
    client = Client(instance.address)
    client.frame()
    client.send(command(ARM, 1))
    assert b"Claim control first" in client.until(b"E")
    assert control.owner is None
    client.sock.close()


def test_peer_outside_the_motorpi_wlan_is_rejected():
    instance, control, stop = start(networks=["10.42.0.0/24"])
    try:
        client = Client(instance.address)
        kind, reason = client.frame()
        assert kind == b"E" and b"MotorPi WLAN" in reason
        with pytest.raises(ConnectionError):
            client.frame()
        assert control.sessions == set()
    finally:
        stop()


def test_default_policy_is_the_access_point_subnet_and_loopback():
    networks = parse_networks()
    assert allowed("10.42.0.57", networks)
    assert allowed("127.0.0.1", networks)
    assert allowed("::ffff:10.42.0.57", networks)
    assert not allowed("192.168.0.20", networks)
    assert not allowed("10.42.1.5", networks)
    assert not allowed("not an address", networks)


def test_second_phone_is_rejected_while_first_owns_control(server):
    instance, control = server
    first = Client(instance.address)
    claim(first)
    second = Client(instance.address)
    assert b"Another phone" in second.until(b"E")
    first.sock.close()
    second.sock.close()


def test_closed_connection_ramps_down_like_radio_loss(server):
    instance, control = server
    client = Client(instance.address)
    claim(client)
    client.send(command(ARM, 1))
    client.send(command(DRIVE, 2, forward=1000, flags=128 | 100))
    client.until(b"S", lambda s: struct.unpack_from("<I", s, 8)[0] == 2)
    time.sleep(0.15)
    client.sock.close()
    deadline = time.monotonic() + 2
    while control.owner is not None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert control.owner is None
    assert control.state in (STOPPING, DISARMED) and control.error == 1


def test_status_is_pushed_periodically(server):
    instance, control = server
    client = Client(instance.address)
    claim(client)
    start = time.monotonic()
    client.until(b"S")
    client.until(b"S")
    assert time.monotonic() - start < 1.0
    client.sock.close()
