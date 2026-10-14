#!/usr/bin/env python3
"""MotorPi read-only log service for the app (port 8081 by default).

A separate process from wifi_server.py on purpose: reading files and running
journalctl must never delay the control loop.

  GET /challenge          -> {"nonce": "<32 hex>"}  (single use, valid 30 s)
  GET /logs               -> [{"name", "label", "available"}, ...]
  GET /logs/<name>?lines=N -> last N lines as UTF-8 text (1..2000, default 200)

Every request except /challenge carries
  X-MotorPi-Auth: <nonce hex>:<HMAC-SHA256(key, b"logs" || nonce || path)[:16] hex>
where path is the request path including the query string, and key is the
16-byte key derived from the app access code (config key_hex).
Only the fixed sources below can be read. Python 3.7 compatible, standard library only.
"""
import argparse
import hashlib
import hmac
import json
import logging
import os
import secrets
import subprocess
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

LOG = logging.getLogger("motorpi.logs")
DEFAULT_PORT = 8081
NONCE_TTL_S = 30
MAX_NONCES = 64
MAX_FAILURES = 5
MAX_LINES = 2000
MAX_TAIL_BYTES = 4 * 1024 * 1024


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


class Auth:
    """Single-use challenges; five failures block everyone until the 30 s window ends."""

    def __init__(self, key, clock=time.monotonic):
        self.key, self.clock = key, clock
        self.lock = threading.Lock()
        self.nonces = OrderedDict()
        self.failures, self.window = 0, clock()

    def challenge(self):
        nonce = secrets.token_bytes(16)
        with self.lock:
            now = self.clock()
            for old in [n for n, issued in self.nonces.items() if now - issued > NONCE_TTL_S]:
                del self.nonces[old]
            while len(self.nonces) >= MAX_NONCES:
                self.nonces.popitem(last=False)
            self.nonces[nonce] = now
        return nonce.hex()

    def verify(self, header, path):
        """Returns None when accepted, else the rejection reason."""
        with self.lock:
            now = self.clock()
            if now - self.window >= NONCE_TTL_S:
                self.failures, self.window = 0, now
            if self.failures >= MAX_FAILURES:
                return "Too many access-code attempts; wait 30 seconds"
            try:
                nonce_hex, mac_hex = (header or "").split(":", 1)
                nonce, mac = bytes.fromhex(nonce_hex), bytes.fromhex(mac_hex)
            except ValueError:
                return "Missing or malformed X-MotorPi-Auth"
            issued = self.nonces.pop(nonce, None)
            if issued is None or now - issued > NONCE_TTL_S:
                return "Challenge unknown, used or expired"
            expected = hmac.new(self.key, b"logs" + nonce + path.encode("utf-8"),
                                hashlib.sha256).digest()[:16]
            if not hmac.compare_digest(expected, mac):
                self.failures += 1
                return "Invalid access code"
            return None


def make_handler(auth, sources, journal=tail_journal):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MotorPiLogs/1"

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
            if url.path == "/challenge":
                return self._send(200, json.dumps({"nonce": auth.challenge()}), "application/json")
            if url.path != "/logs" and not url.path.startswith("/logs/"):
                return self._send(404, "Not found")
            reason = auth.verify(self.headers.get("X-MotorPi-Auth"), self.path)
            if reason is not None:
                LOG.warning("Log request rejected: %s", reason)
                return self._send(429 if reason.startswith("Too many") else 403, reason)
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
        key = bytes.fromhex(json.load(source)["key_hex"])
    if len(key) != 16:
        raise SystemExit("key_hex must contain 16 bytes")
    server = ThreadingHTTPServer((args.host, args.port),
                                 make_handler(Auth(key), default_sources(args.log_dir)))
    server.daemon_threads = True
    LOG.info("Serving logs from %s and the journal on %s:%d", args.log_dir, args.host, args.port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
