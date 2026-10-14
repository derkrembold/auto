"""WLAN transport over a real loopback socket, simulation only (no watchdog socket)."""
import hashlib
import hmac
import socket
import struct
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_core import Config, Control, ARM, DRIVE, ARMED, STOPPING, DISARMED
from wifi_server import Server

KEY = bytes(range(16))


@pytest.fixture
def server():
    control = Control(Config(KEY.hex()), time.monotonic)
    lock, done = threading.Lock(), threading.Event()
    instance = Server(control, lock, "127.0.0.1", 0)

    def loop():
        while not done.is_set():
            instance.poll(0.02)
            with lock:
                control.tick()

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    yield instance, control
    done.set()
    thread.join(timeout=2)
    instance.close()


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


def command(nonce, op, seq, forward=0, steer=0, flags=0):
    body = struct.pack("<BIhhB", op, seq, forward, steer, flags)
    return body + hmac.new(KEY, nonce + body, hashlib.sha256).digest()[:10]


def authenticate(client):
    kind, nonce = client.frame()
    assert kind == b"C" and len(nonce) == 16
    client.send(b"\x00" + hmac.new(KEY, b"auth" + nonce, hashlib.sha256).digest()[:16])
    client.until(b"S", lambda status: status[2] & 2)
    return nonce


def test_authenticated_drive_is_acknowledged_by_sequence(server):
    instance, control = server
    client = Client(instance.address)
    nonce = authenticate(client)
    client.send(command(nonce, ARM, 1))
    status = client.until(b"S", lambda s: struct.unpack_from("<I", s, 8)[0] == 1)
    assert status[1] == ARMED
    client.send(command(nonce, DRIVE, 2, forward=1000, flags=128 | 100))
    status = client.until(b"S", lambda s: struct.unpack_from("<I", s, 8)[0] == 2)
    assert control.target == (1200, 1200)
    client.sock.close()


def test_wrong_code_gets_reason_and_no_session(server):
    instance, control = server
    client = Client(instance.address)
    client.frame()
    client.send(b"\x00" + bytes(16))
    assert b"Invalid access code" in client.until(b"E")
    assert control.owner is None
    client.sock.close()


def test_second_phone_is_rejected_while_first_owns_control(server):
    instance, control = server
    first = Client(instance.address)
    authenticate(first)
    second = Client(instance.address)
    assert b"Another phone" in second.until(b"E")
    first.sock.close()
    second.sock.close()


def test_closed_connection_ramps_down_like_radio_loss(server):
    instance, control = server
    client = Client(instance.address)
    nonce = authenticate(client)
    client.send(command(nonce, ARM, 1))
    client.send(command(nonce, DRIVE, 2, forward=1000, flags=128 | 100))
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
    authenticate(client)
    start = time.monotonic()
    client.until(b"S")
    client.until(b"S")
    assert time.monotonic() - start < 1.0
    client.sock.close()
