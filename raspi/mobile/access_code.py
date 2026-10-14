"""Short random access codes; BLE HMAC retains its 16-byte key format."""
import hashlib
import re
import secrets

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_code():
    return "".join(secrets.choice(ALPHABET) for _ in range(8))


def derive_key(code):
    normalized = re.sub(r"[\s-]", "", code).upper()
    if len(normalized) != 8 or any(char not in ALPHABET for char in normalized):
        raise ValueError("Expected eight characters, excluding I/O/0/1")
    return hashlib.sha256(("MotorPi access code v1:" + normalized).encode("utf-8")).digest()[:16]
