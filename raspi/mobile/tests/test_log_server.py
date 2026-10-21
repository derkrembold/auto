"""Read-only log service over a real loopback HTTP server; no journal access needed."""
import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from log_server import BoundedServer, default_sources, make_handler, tail_file


@pytest.fixture
def server(tmp_path):
    (tmp_path / "watchdog.log").write_text("".join("line %d\n" % i for i in range(500)))
    journal_calls = []

    def journal(unit, lines):
        journal_calls.append((unit, lines))
        return "journal of %s\n" % unit

    instance = BoundedServer(("127.0.0.1", 0),
                             make_handler(default_sources(str(tmp_path)), journal))
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % instance.server_address[1], journal_calls
    instance.shutdown()
    instance.server_close()


def get(base, path):
    try:
        with urllib.request.urlopen(base + path) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def test_lists_sources_and_tails_a_file(server):
    base, _ = server
    status, body = get(base, "/logs")
    assert status == 200
    listing = {item["name"]: item for item in json.loads(body)}
    assert listing["watchdog"]["available"] is True
    assert listing["motorcontrol"]["available"] is False
    assert listing["mobile"]["available"] is True
    status, body = get(base, "/logs/watchdog?lines=3")
    assert status == 200
    assert body == "line 497\nline 498\nline 499\n"


def test_journal_sources_go_through_journalctl_with_clamped_lines(server):
    base, calls = server
    status, body = get(base, "/logs/mobile?lines=99999")
    assert (status, body) == (200, "journal of motorpi-mobile\n")
    assert calls == [("motorpi-mobile", 2000)]


def test_only_fixed_sources_are_served(server):
    base, _ = server
    assert get(base, "/logs/../../etc/passwd")[0] == 404
    assert get(base, "/challenge")[0] == 404


def test_client_outside_the_motorpi_wlan_gets_no_response(tmp_path):
    instance = BoundedServer(("127.0.0.1", 0), make_handler(default_sources(str(tmp_path))),
                             networks=["10.42.0.0/24"])
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.create_connection(instance.server_address) as sock:
            sock.sendall(b"GET /logs HTTP/1.0\r\n\r\n")
            sock.settimeout(2)
            assert sock.recv(4096) == b""
    finally:
        instance.shutdown()
        instance.server_close()


def test_tail_handles_files_larger_than_one_block(tmp_path):
    path = tmp_path / "big.log"
    path.write_text("".join("%06d %s\n" % (i, "x" * 200) for i in range(2000)))
    assert tail_file(str(path), 2).splitlines()[0].startswith("001998 ")


@pytest.fixture
def limited(tmp_path):
    """Two client slots, short timeouts."""
    instance = BoundedServer(("127.0.0.1", 0),
                             make_handler(default_sources(str(tmp_path)),
                                          timeout=0.3, deadline=1.0),
                             max_clients=2)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield instance.server_address
    instance.shutdown()
    instance.server_close()


def closed_within(sock, seconds):
    """True when the server closes the connection before `seconds` pass."""
    sock.settimeout(seconds)
    try:
        while sock.recv(4096):
            pass
        return True
    except socket.timeout:
        return False
    except ConnectionResetError:
        return True


def test_silent_client_is_dropped_after_socket_timeout(limited):
    with socket.create_connection(limited) as sock:
        sock.sendall(b"GET /logs HTTP/1.0\r\n")  # headers never finish
        assert closed_within(sock, 2)


def test_trickling_client_is_cut_by_connection_deadline(limited):
    with socket.create_connection(limited) as sock:
        sock.sendall(b"GET /logs HTTP/1.0\r\n")
        start = time.monotonic()
        with pytest.raises(OSError):
            for _ in range(50):  # one header byte every 0.1 s keeps the socket timeout happy
                sock.sendall(b"X")
                time.sleep(0.1)
        assert time.monotonic() - start < 2


def test_connections_beyond_the_cap_are_closed_at_once(limited):
    held = [socket.create_connection(limited) for _ in range(2)]
    try:
        time.sleep(0.05)
        with socket.create_connection(limited) as extra:
            assert closed_within(extra, 0.2)
    finally:
        for sock in held:
            sock.close()
    time.sleep(0.1)
    base = "http://%s:%d" % limited
    with urllib.request.urlopen(base + "/logs") as response:
        assert response.status == 200
