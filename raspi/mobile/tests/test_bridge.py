"""Bridge recovery logic against a scripted fake watchdog client (no sockets, no motors)."""
import logging
import struct
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge
from bridge import Unreachable, MotorFault, WatchdogClient, worker
from control_core import (Config, Control, CLAIM, ARM, ARMED, DISARMED, FAULT,
                          ERR_UNREACHABLE, ERR_MOTOR_STALLED)

bridge.PROBE_INTERVAL_S = 0.05


class FakeWatchdog:
    """Simulates the watchdog IPC: `powered` = motor fuse on, `stalled` = latched sys_error."""
    def __init__(self, powered=True):
        self.powered = powered
        self.stalled = set()
        self.commands = []
        self.connection = None
        self.overcurrent = False

    def connect(self):
        self.connection = True

    def close(self):
        self.commands.append("DISCONNECTED")
        self.connection = None

    def command(self, text, timeout=0.5):
        if self.connection is None:
            raise AssertionError("command on closed connection: " + text)
        self.commands.append(text)
        return "OK"

    def check_status(self, motor, timeout=0.5):
        self.commands.append("status %d" % motor)
        if not self.powered:
            raise Unreachable("Motor %d not reachable: OK ret=-5" % motor)
        if motor in self.stalled:
            raise MotorFault(motor, "OK ret=0 kickstart=3 sys_error=-65")

    def check_current(self, timeout=0.5):
        if self.overcurrent:
            raise RuntimeError("Overcurrent or invalid current measurement")

    def reset(self, motor):
        self.commands.append("reset %d" % motor)
        self.stalled.discard(motor)

    def speeds(self, values):
        self.commands.append("speeds %d %d" % tuple(values))


def start(fake):
    config = Config(live=True, mapping_verified=True, left_dir="cw", right_dir="ccw")
    control = Control(config, time.monotonic)
    lock, shutdown = threading.Lock(), threading.Event()
    thread = threading.Thread(target=worker, args=(control, lock, shutdown, logging.getLogger("t"), fake),
                              daemon=True)
    thread.start()
    return control, lock, shutdown, thread


def wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def drive(control, lock):
    with lock:
        control.state, control.last_input, control.target = ARMED, time.monotonic(), (700, -700)


def test_fuse_off_at_start_blocks_until_power_returns():
    fake = FakeWatchdog(powered=False)
    control, lock, shutdown, thread = start(fake)
    assert wait_for(lambda: control.error == ERR_UNREACHABLE)
    time.sleep(0.2)
    assert not control.ready and control.state == DISARMED
    fake.powered = True
    assert wait_for(lambda: control.ready), "Start must re-enable once the motors answer"
    shutdown.set(); thread.join(2)


def test_power_loss_while_driving_zeroes_and_recovers():
    fake = FakeWatchdog()
    control, lock, shutdown, thread = start(fake)
    assert wait_for(lambda: control.ready)
    drive(control, lock)
    assert wait_for(lambda: "speeds 700 -700" in fake.commands)
    fake.powered = False
    assert wait_for(lambda: control.error == ERR_UNREACHABLE)
    assert control.output == (0, 0) and not control.ready
    assert "speeds 0 0" in fake.commands[fake.commands.index("speeds 700 -700"):]
    fake.powered = True
    assert wait_for(lambda: control.ready)
    assert control.state == DISARMED, "recovery never re-arms by itself; the app must press Start"
    shutdown.set(); thread.join(2)


def test_stall_without_motor_power_is_reset_and_needs_new_start():
    fake = FakeWatchdog()
    control, lock, shutdown, thread = start(fake)
    assert wait_for(lambda: control.ready)
    drive(control, lock)
    assert wait_for(lambda: "speeds 700 -700" in fake.commands)
    fake.stalled.add(1)
    assert wait_for(lambda: control.error == ERR_MOTOR_STALLED)
    assert wait_for(lambda: control.ready)
    tail = fake.commands[fake.commands.index("speeds 700 -700") + 1:]
    assert "reset 1" in tail and "speeds 0 0" in tail[:tail.index("reset 1")]
    assert control.state == DISARMED and control.output == (0, 0)
    assert control.error == ERR_MOTOR_STALLED, "reason stays visible until the next Start"
    shutdown.set(); thread.join(2)


def test_overcurrent_still_latches_permanently():
    fake = FakeWatchdog()
    control, lock, shutdown, thread = start(fake)
    assert wait_for(lambda: control.ready)
    drive(control, lock)
    fake.overcurrent = True
    thread.join(2)
    assert control.state == FAULT and fake.commands[-1] == "DISCONNECTED"


def test_late_reply_forces_reconnect():
    class Late:
        def __init__(self):
            self.sent = []
        def send(self, text):
            self.sent.append(text)
        def poll(self, timeout):
            return False
        def close(self):
            pass
    client = WatchdogClient(Config())
    client.connection = Late()
    try:
        client.check_status(0, timeout=0.01)
    except Unreachable as exc:
        assert exc.stale
    else:
        raise AssertionError("timeout must be reported as unreachable")


def test_status_reply_parsing():
    client = WatchdogClient(Config())
    replies = iter(["OK ret=-5 timeout=None checksum=None kickstart=None sys_error=None",
                    "OK ret=0 timeout=0 checksum=0 kickstart=3 sys_error=-65",
                    "OK ret=0 timeout=0 checksum=0 kickstart=0 sys_error=0"])
    client.command = lambda text, timeout=0.5: next(replies)
    for expected in (Unreachable, MotorFault):
        try:
            client.check_status(0)
        except expected:
            pass
        else:
            raise AssertionError(expected)
    client.check_status(0)


def test_arm_explains_missing_motors():
    control = Control(Config(), time.monotonic)
    control.connect("p")
    control.receive("p", bytes([CLAIM]))
    control.unavailable(ERR_UNREACHABLE)
    try:
        control.receive("p", struct.pack("<BIhhB", ARM, 1, 0, 0, 0))
    except ValueError as exc:
        assert "motor fuse" in str(exc)
    else:
        raise AssertionError("Start must be refused while motors are unreachable")
