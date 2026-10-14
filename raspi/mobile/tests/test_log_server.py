"""Read-only log service over a real loopback HTTP server; no journal access needed."""
import hashlib
import hmac
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from access_code import derive_key
from log_server import Auth, default_sources, make_handler, tail_file
from http.server import ThreadingHTTPServer

KEY = bytes(range(16))


@pytest.fixture
def server(tmp_path):
    (tmp_path / "watchdog.log").write_text("".join("line %d\n" % i for i in range(500)))
    journal_calls = []

    def journal(unit, lines):
        journal_calls.append((unit, lines))
        return "journal of %s\n" % unit

    clock = [0.0]
    auth = Auth(KEY, clock=lambda: clock[0])
    instance = ThreadingHTTPServer(("127.0.0.1", 0),
                                   make_handler(auth, default_sources(str(tmp_path)), journal))
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % instance.server_address[1], journal_calls, clock
    instance.shutdown()
    instance.server_close()


def get(base, path, key=KEY, nonce=None, tamper=False):
    if nonce is None:
        with urllib.request.urlopen(base + "/challenge") as response:
            nonce = json.loads(response.read())["nonce"]
    mac = hmac.new(key, b"logs" + bytes.fromhex(nonce) + path.encode(), hashlib.sha256).digest()[:16]
    if tamper:
        path = path.replace("200", "201")
    request = urllib.request.Request(base + path, headers={"X-MotorPi-Auth": nonce + ":" + mac.hex()})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def test_lists_sources_and_tails_a_file(server):
    base, _, _ = server
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
    base, calls, _ = server
    status, body = get(base, "/logs/mobile?lines=99999")
    assert (status, body) == (200, "journal of motorpi-mobile\n")
    assert calls == [("motorpi-mobile", 2000)]


def test_rejects_wrong_code_reused_nonce_and_tampered_path(server):
    base, _, _ = server
    assert get(base, "/logs", key=derive_key("ABCD2345"))[0] == 403
    with urllib.request.urlopen(base + "/challenge") as response:
        nonce = json.loads(response.read())["nonce"]
    assert get(base, "/logs", nonce=nonce)[0] == 200
    assert get(base, "/logs", nonce=nonce)[0] == 403
    assert get(base, "/logs/watchdog?lines=200", tamper=True)[0] == 403
    assert get(base, "/logs/../../etc/passwd")[0] == 404


def test_five_failures_block_until_window_ends(server):
    base, _, clock = server
    for _ in range(5):
        assert get(base, "/logs", key=bytes(16))[0] == 403
    assert get(base, "/logs")[0] == 429
    clock[0] += 31
    assert get(base, "/logs")[0] == 200


def test_expired_challenge_is_rejected(server):
    base, _, clock = server
    with urllib.request.urlopen(base + "/challenge") as response:
        nonce = json.loads(response.read())["nonce"]
    clock[0] += 31
    assert get(base, "/logs", nonce=nonce)[0] == 403


def test_tail_handles_files_larger_than_one_block(tmp_path):
    path = tmp_path / "big.log"
    path.write_text("".join("%06d %s\n" % (i, "x" * 200) for i in range(2000)))
    assert tail_file(str(path), 2).splitlines()[0].startswith("001998 ")


def test_app_golden_vector():
    """Same vector as mobile_app/test/log_client_test.dart."""
    nonce = bytes(range(16, 32))
    mac = hmac.new(KEY, b"logs" + nonce + b"/logs/watchdog?lines=200", hashlib.sha256).digest()[:16]
    assert mac.hex() == GOLDEN


GOLDEN = "ed7e8826e793b78dc19da8b3586f91de"
