"""Hardware-independent, authenticated mobile control. Python 3.7 compatible."""
import hashlib
import hmac
import secrets
import struct
from dataclasses import dataclass

SERVICE_UUID = "bc790001-6a35-4c63-9419-00d9e185a101"
CHALLENGE_UUID = "bc790002-6a35-4c63-9419-00d9e185a101"
COMMAND_UUID = "bc790003-6a35-4c63-9419-00d9e185a101"
STATUS_UUID = "bc790004-6a35-4c63-9419-00d9e185a101"
AUTH, ARM, DRIVE, STOP = 0, 1, 2, 3
DISARMED, ARMED, STOPPING, FAULT = 0, 1, 2, 3
# Status error codes. 1 and 3 as before; 4/5 clear themselves once the hardware answers.
ERR_INPUT_LOST, ERR_HARDWARE, ERR_UNREACHABLE, ERR_MOTOR_STALLED = 1, 3, 4, 5


@dataclass
class Config:
    key_hex: str
    live: bool = False
    left: int = 0
    right: int = 1
    left_dir: str = "unknown"
    right_dir: str = "unknown"
    mapping_verified: bool = False
    max_rpm: int = 1200
    deadzone_rpm: int = 500
    heartbeat_s: float = 0.6
    ramp_s: float = 1.0
    socket_path: str = "/tmp/motorwatchdog.sock"

    def __post_init__(self):
        if len(bytes.fromhex(self.key_hex)) != 16:
            raise ValueError("key_hex must contain 16 random bytes")
        if self.left == self.right or self.left not in range(4) or self.right not in range(4):
            raise ValueError("Two distinct motor instances 0..3 are required")
        if not 0 < self.max_rpm <= 1200 or not 0 <= self.deadzone_rpm < self.max_rpm:
            raise ValueError("Invalid RPM limits")
        if not 0.2 <= self.heartbeat_s <= 1 or not 0.2 <= self.ramp_s <= 2:
            raise ValueError("Invalid heartbeat/ramp duration")
        if self.live and (not self.mapping_verified or
                          self.left_dir not in ("cw", "ccw") or
                          self.right_dir not in ("cw", "ccw")):
            raise ValueError("Live mode requires a verified motor mapping and both directions")


class Control:
    """Called under the server's lock; tick() has no I/O and never blocks."""
    def __init__(self, config, clock):
        self.config, self.clock = config, clock
        self.key = bytes.fromhex(config.key_hex)
        self.sessions = {}
        self.owner = None
        self.state = DISARMED
        self.error = 0
        self.seq = 0
        self.last_input = 0.0
        self.output = (0, 0)
        self.target = (0, 0)
        self.stop_started = None
        self.stop_origin = (0, 0)
        self.ready = not config.live
        self.auth_failures = 0
        self.auth_window = self.clock()

    def challenge(self, peer):
        if not peer:
            raise ValueError("Missing Bluetooth device identity")
        if self.owner is not None and self.owner != peer:
            raise ValueError("Another phone owns the control session")
        if self.owner == peer:
            self.stop()
            self.owner = None
        # Bound memory even if many unauthenticated devices ask for a challenge.
        if len(self.sessions) >= 8 and peer not in self.sessions:
            self.sessions.clear()
        nonce = secrets.token_bytes(16)
        self.sessions[peer] = (nonce, self.clock())
        return nonce

    def receive(self, peer, packet):
        if peer not in self.sessions:
            raise ValueError("Read challenge first")
        nonce, issued = self.sessions[peer]
        if len(packet) == 17 and packet[0] == AUTH:
            now = self.clock()
            if now - self.auth_window >= 30:
                self.auth_failures, self.auth_window = 0, now
            if self.auth_failures >= 5:
                raise ValueError("Too many access-code attempts; wait 30 seconds")
            if self.clock() - issued > 30 or self.owner not in (None, peer):
                raise ValueError("Challenge expired or control occupied")
            expected = hmac.new(self.key, b"auth" + nonce, hashlib.sha256).digest()[:16]
            if not hmac.compare_digest(expected, packet[1:]):
                self.auth_failures += 1
                raise ValueError("Invalid access code")
            if self.owner == peer:
                raise ValueError("Already authenticated; read a fresh challenge")
            self.owner, self.seq = peer, 0
            return
        if len(packet) != 20 or self.owner != peer:
            raise ValueError("Not authenticated or invalid packet size")
        body, tag = packet[:10], packet[10:]
        expected = hmac.new(self.key, nonce + body, hashlib.sha256).digest()[:10]
        if not hmac.compare_digest(expected, tag):
            raise ValueError("Invalid command signature")
        op, seq, forward, steer, flags = struct.unpack("<BIhhB", body)
        held, limit = bool(flags & 128), flags & 127
        if seq <= self.seq or abs(forward) > 1000 or abs(steer) > 1000 or limit > 100:
            raise ValueError("Stale sequence or invalid control values")
        if op not in (ARM, DRIVE, STOP):
            raise ValueError("Unknown operation")
        if op == ARM:
            if forward or steer or flags or self.state == STOPPING or self.output != (0, 0):
                raise ValueError("Release all controls before Start")
            if not self.ready:
                if self.error in (ERR_UNREACHABLE, ERR_MOTOR_STALLED):
                    raise ValueError("Motors not reachable or not turning; check the motor fuse")
                raise ValueError("Watchdog not ready; check local service")
            if self.state == FAULT:
                raise ValueError("Fault is latched; local operator must inspect/restart service")
            self.state, self.error = ARMED, 0
            self.target = (0, 0)
        elif op == STOP:
            self.stop()
        elif self.state != ARMED:
            raise ValueError("Press Start first")
        elif not held:
            # Releasing the touch surface / controller dead-man requires a new Start.
            if self.output != (0, 0) or self.target != (0, 0):
                self.stop()
        else:
            self.target = self.mix(forward, steer, limit)
        self.seq, self.last_input = seq, self.clock()

    def mix(self, forward, steer, limit=100):
        result = []
        for raw, direction in ((forward + steer, self.config.left_dir),
                               (forward - steer, self.config.right_dir)):
            rpm = round(max(-1000, min(1000, raw)) * self.config.max_rpm * limit / 100000)
            if abs(rpm) < self.config.deadzone_rpm:
                rpm = 0
            result.append(-rpm if direction == "ccw" else rpm)
        return tuple(result)

    def stop(self, error=0):
        if self.state == FAULT:
            return
        self.target = (0, 0)
        if error and self.ready:  # keep a pending hardware reason visible
            self.error = error
        if self.state == STOPPING:
            return  # repeated Stop/heartbeat loss must not extend the ramp
        self.stop_origin, self.stop_started = self.output, self.clock()
        self.state = STOPPING if self.output != (0, 0) else DISARMED

    def fault(self, error=3):
        # A hardware fault must not be followed by nonzero ramp commands re-arming a stalled motor.
        self.state, self.error = FAULT, error
        self.output = self.target = (0, 0)

    def unavailable(self, error):
        # Hardware not answering or not turning: zero at once (no ramp on a lost motor),
        # block Start until the bridge sees every device answer cleanly again.
        if self.state == FAULT:
            return
        self.ready = False
        self.state, self.error = DISARMED, error
        self.output = self.target = (0, 0)

    def available(self):
        # The error stays visible until the next Start, which clears it.
        if self.state != FAULT:
            self.ready = True

    def disconnect(self, peer):
        self.sessions.pop(peer, None)
        if self.owner == peer:
            self.stop(error=1)
            self.owner = None

    def tick(self):
        now = self.clock()
        if self.state == ARMED and now - self.last_input > self.config.heartbeat_s:
            self.stop(error=1)
        if self.state == STOPPING:
            factor = max(0.0, 1 - (now - self.stop_started) / self.config.ramp_s)
            self.output = tuple(round(v * factor) for v in self.stop_origin)
            if factor <= 0:
                self.state, self.output = DISARMED, (0, 0)
        elif self.state == ARMED:
            self.output = self.target
        else:
            self.output = (0, 0)
        return self.output

    def status(self):
        # 20 bytes, fits the default BLE ATT payload without MTU negotiation.
        flags = int(self.config.live) | (int(self.owner is not None) << 1) | (int(self.ready) << 2)
        return struct.pack("<BBBBhhIHH4x", 1, self.state, flags, self.error,
                           *self.output, self.seq, self.config.max_rpm,
                           round(self.config.heartbeat_s * 1000))
