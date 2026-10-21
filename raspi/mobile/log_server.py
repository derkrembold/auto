#!/usr/bin/env python3
"""MotorPi read-only log service for the app (port 8081 by default).

A separate process from wifi_server.py on purpose: reading files and running
journalctl must never delay the control loop.

  GET /logs               -> [{"name", "label", "available"}, ...]
  GET /logs/<name>?lines=N -> last N lines as UTF-8 text (1..2000, default 200)

No access code: only clients on the MotorPi WLAN are served (network_policy.py),
others are closed without a response. Only the fixed sources below can be read.
Connections are capped (MAX_CLIENTS) and time-limited, so clients cannot exhaust
the Pi. Python 3.7 compatible, standard library only.
"""
import argparse
import json
import logging
import os
import socket
import subprocess
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from network_policy import allowed, parse_networks

LOG = logging.getLogger("motorpi.logs")
DEFAULT_PORT = 8081
MAX_LINES = 2000
MAX_TAIL_BYTES = 4 * 1024 * 1024
# Unauthenticated clients must not be able to pile up threads/sockets on the Pi.
MAX_CLIENTS = 8
SOCKET_TIMEOUT_S = 10    # per read/write, covers request line and headers
CONNECTION_DEADLINE_S = 30  # whole connection, so trickling bytes cannot hold a slot


def default_sources(log_dir):
    """name -> (label, kind, target); kind is "file" or "journal"."""
    files = [("watchdog", "Watchdog"), ("joystick", "joystick.py"),
             ("motorcontrol", "motorcontrol.py"),
             ("validate_speed", "validate_speed.py"),
             ("capture_step_response", "capture_step_response.py"),
             ("validate_lin_stress", "validate_lin_stress.py")]
    units = [("mobile", "Steuerdienst", "motorpi-mobile"),
             ("session", "Fahrsitzung", "motorpi-driving-session"),
             ("ap", "WLAN-Access-Point", "motorpi-ap"),
             ("dhcp", "DHCP/DNS", "motorpi-dhcp"),
             ("download", "App-Download", "motorpi-download"),
             ("logs", "Log-Dienst", "motorpi-logs")]
    sources = OrderedDict()
    for name, label in files:
        sources[name] = (label + " (" + name + ".log)", "file", os.path.join(log_dir, name + ".log"))
    for name, label, unit in units:
        sources[name] = (label + " (" + unit + ")", "journal", unit)
    return sources


def tail_file(path, lines):
    with open(path, "rb") as source:
        source.seek(0, os.SEEK_END)
        position = source.tell()
        data = b""
        while position > 0 and data.count(b"\n") <= lines and len(data) < MAX_TAIL_BYTES:
            step = min(65536, position)
            position -= step
            source.seek(position)
            data = source.read(step) + data
    return b"\n".join(data.splitlines()[-lines:]).decode("utf-8", "replace") + "\n"


def tail_journal(unit, lines):
    result = subprocess.run(
        ["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    text = result.stdout.decode("utf-8", "replace")
    if result.returncode != 0 or not text.strip():
        text += result.stderr.decode("utf-8", "replace")
    return text


class BoundedServer(ThreadingHTTPServer):
    """At most max_clients connections at once; further ones are closed immediately."""
    daemon_threads = True

    def __init__(self, address, handler, max_clients=MAX_CLIENTS, networks=None):
        super().__init__(address, handler)
        self.slots = threading.BoundedSemaphore(max_clients)
        self.networks = parse_networks(networks)

    def verify_request(self, request, client_address):
        if allowed(client_address[0], self.networks):
            return True
        LOG.warning("Log client %s rejected: not on the MotorPi WLAN", client_address[0])
        return False

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            LOG.warning("Too many log clients; dropping %s", client_address[0])
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def make_handler(sources, journal=tail_journal,
                 timeout=SOCKET_TIMEOUT_S, deadline=CONNECTION_DEADLINE_S):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MotorPiLogs/1"

        def setup(self):
            self.timeout = timeout
            super().setup()
            self._deadline = threading.Timer(deadline, self._abort)
            self._deadline.daemon = True
            self._deadline.start()

        def _abort(self):
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        def finish(self):
            self._deadline.cancel()
            super().finish()

        def log_message(self, format_, *args):
            LOG.info("%s %s", self.address_string(), format_ % args)

        def _send(self, status, body, content_type="text/plain; charset=utf-8"):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlsplit(self.path)
            if url.path != "/logs" and not url.path.startswith("/logs/"):
                return self._send(404, "Not found")
            if url.path == "/logs":
                listing = [{"name": name, "label": label,
                            "available": kind == "journal" or os.path.isfile(target)}
                           for name, (label, kind, target) in sources.items()]
                return self._send(200, json.dumps(listing), "application/json")
            name = unquote(url.path[len("/logs/"):])
            if name not in sources:
                return self._send(404, "Unknown log source")
            try:
                lines = int(parse_qs(url.query).get("lines", ["200"])[0])
            except ValueError:
                return self._send(400, "lines must be a number")
            lines = max(1, min(MAX_LINES, lines))
            label, kind, target = sources[name]
            try:
                text = tail_file(target, lines) if kind == "file" else journal(target, lines)
            except FileNotFoundError:
                return self._send(404, "%s does not exist yet" % target)
            except (OSError, subprocess.SubprocessError) as exc:
                return self._send(500, "Reading %s failed: %s" % (label, exc))
            return self._send(200, text)

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/etc/motorpi-mobile/config.json")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--log-dir", default="/home/pi/auto")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with open(args.config) as source:
        networks = json.load(source).get("allowed_networks")
    server = BoundedServer((args.host, args.port), make_handler(default_sources(args.log_dir)),
                           networks=networks)
    LOG.info("Serving logs from %s and the journal on %s:%d", args.log_dir, args.host, args.port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
