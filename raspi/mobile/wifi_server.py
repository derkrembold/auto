#!/usr/bin/env python3
"""MotorPi WLAN control server: the control protocol (version 2) over plain TCP.

Frames in both directions: one length byte, then the payload.
  Pi -> app:  b"S" + 20-byte status (immediately, after every accepted packet,
              and every 200 ms)
              b"E" + UTF-8 reason (rejected packet; the connection stays open)
  App -> Pi:  1-byte claim (0x00) or 10-byte command, see control_core.
Only peers from the MotorPi WLAN are accepted (network_policy.py); others get
an E frame and are closed. One TCP connection is one peer identity; closing it
stops like a radio loss. Python 3.7 compatible, standard library only.
"""
import argparse
import json
import logging
import selectors
import signal
import socket
import threading
import time

from bridge import worker
from control_core import Config, Control
from network_policy import REJECTION, allowed, parse_networks

LOG = logging.getLogger("motorpi.mobile")
DEFAULT_PORT = 8765
MAX_CLIENTS = 4
STATUS_INTERVAL_S = 0.2


def frame(kind, payload):
    data = kind + bytes(payload)
    if len(data) > 255:
        data = data[:255]
    return bytes([len(data)]) + data


class Peer:
    def __init__(self, sock, address):
        self.sock = sock
        self.name = "tcp:%s:%d" % address[:2]
        self.inbox = b""
        self.outbox = b""
        self.closed = False


class Server:
    """Single-threaded selector loop; Control is shared with the bridge worker under lock."""

    def __init__(self, control, lock, host, port, clock=time.monotonic, networks=None):
        self.control, self.lock, self.clock = control, lock, clock
        self.networks = parse_networks(networks)
        self.selector = selectors.DefaultSelector()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind((host, port))
        self.listener.listen(MAX_CLIENTS)
        self.listener.setblocking(False)
        self.address = self.listener.getsockname()
        self.selector.register(self.listener, selectors.EVENT_READ)
        self.peers = {}
        self.next_status = 0.0

    def _accept(self):
        sock, address = self.listener.accept()
        if len(self.peers) >= MAX_CLIENTS:
            sock.close()
            return
        sock.setblocking(False)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        peer = Peer(sock, address)
        self.peers[sock] = peer
        self.selector.register(sock, selectors.EVENT_READ)
        LOG.info("WLAN peer %s connected", peer.name)
        if not allowed(address[0], self.networks):
            LOG.warning("Peer %s rejected: not on the MotorPi WLAN", peer.name)
            peer.closed = True  # close once the reason has been flushed
            self._queue(peer, frame(b"E", REJECTION.encode("utf-8")))
            return
        try:
            with self.lock:
                self.control.connect(peer.name)
                status = self.control.status()
            self._queue(peer, frame(b"S", status))
        except ValueError as exc:
            LOG.warning("WLAN session rejected: %s", exc)
            peer.closed = True  # close once the reason has been flushed
            self._queue(peer, frame(b"E", str(exc).encode("utf-8")))

    def _queue(self, peer, data):
        peer.outbox += data
        self._flush(peer)

    def _flush(self, peer):
        try:
            while peer.outbox:
                sent = peer.sock.send(peer.outbox)
                peer.outbox = peer.outbox[sent:]
        except (BlockingIOError, InterruptedError):
            pass
        except OSError:
            self._drop(peer)
            return
        if peer.sock not in self.peers:
            return
        if peer.closed and not peer.outbox:
            self._drop(peer)
            return
        events = selectors.EVENT_READ | (selectors.EVENT_WRITE if peer.outbox else 0)
        self.selector.modify(peer.sock, events)
        # A client that does not read cannot make the Pi buffer unboundedly.
        if len(peer.outbox) > 4096:
            self._drop(peer)

    def _drop(self, peer):
        if self.peers.pop(peer.sock, None) is None:
            return
        try:
            self.selector.unregister(peer.sock)
        except (KeyError, ValueError):
            pass
        peer.sock.close()
        with self.lock:
            self.control.disconnect(peer.name)
        LOG.info("WLAN peer %s disconnected", peer.name)

    def _receive(self, peer):
        try:
            data = peer.sock.recv(1024)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b""
        if not data:
            self._drop(peer)
            return
        peer.inbox += data
        while peer.inbox and len(peer.inbox) > peer.inbox[0]:
            size = peer.inbox[0]
            packet, peer.inbox = peer.inbox[1:1 + size], peer.inbox[1 + size:]
            self._handle(peer, packet)
            if peer.sock not in self.peers:
                return
        if len(peer.inbox) > 64:
            self._drop(peer)

    def _handle(self, peer, packet):
        try:
            with self.lock:
                self.control.receive(peer.name, packet)
                status = self.control.status()
            if packet == b"\x00":
                LOG.info("WLAN control claimed by %s", peer.name)
            self._queue(peer, frame(b"S", status))
        except ValueError as exc:
            LOG.warning("WLAN command rejected: %s", exc)
            self._queue(peer, frame(b"E", str(exc).encode("utf-8")))

    def poll(self, timeout):
        for key, events in self.selector.select(timeout):
            if key.fileobj is self.listener:
                self._accept()
                continue
            peer = self.peers.get(key.fileobj)
            if peer is None:
                continue
            if events & selectors.EVENT_WRITE:
                self._flush(peer)
            if events & selectors.EVENT_READ and peer.sock in self.peers:
                self._receive(peer)
        now = self.clock()
        if now >= self.next_status:
            self.next_status = now + STATUS_INTERVAL_S
            with self.lock:
                status = frame(b"S", self.control.status())
            for peer in list(self.peers.values()):
                self._queue(peer, status)

    def close(self):
        for peer in list(self.peers.values()):
            self._drop(peer)
        self.selector.close()
        self.listener.close()


def load_config(path, live):
    with open(path) as source:
        data = json.load(source)
    host = data.pop("listen_host", "0.0.0.0")
    port = int(data.pop("listen_port", DEFAULT_PORT))
    networks = data.pop("allowed_networks", None)
    data.pop("key_hex", None)  # access code of protocol version 1, no longer used
    configured_live = data.get("live", False)
    if live and not configured_live:
        raise SystemExit("The local configuration has not been commissioned for live control")
    data["live"] = bool(live and configured_live)
    return Config(**data), host, port, networks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/etc/motorpi-mobile/config.json")
    parser.add_argument("--live", action="store_true",
                        help="Explicit per-start hardware consent; config must also authorize live mode")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config, host, port, networks = load_config(args.config, args.live)
    control = Control(config, time.monotonic)
    lock, shutdown = threading.Lock(), threading.Event()
    server = Server(control, lock, host, port, networks=networks)
    thread = threading.Thread(target=worker, args=(control, lock, shutdown, LOG), daemon=True)
    thread.start()
    stop_at = []

    def stop_service(signum, frame_):
        with lock:
            control.ready = False
            control.stop()
        if not stop_at:
            stop_at.append(time.monotonic() + config.ramp_s + 0.3)

    signal.signal(signal.SIGTERM, stop_service)
    signal.signal(signal.SIGINT, stop_service)
    LOG.info("Listening on %s:%d in %s mode", host, port,
             "LIVE" if config.live else "SIMULATION (no motor socket)")
    try:
        while not (stop_at and time.monotonic() >= stop_at[0]):
            if shutdown.is_set() and not thread.is_alive():
                break
            server.poll(0.05)
    finally:
        shutdown.set()
        thread.join(timeout=2)
        server.close()
    if control.state == 3:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
