"""Linux-only integration test with a private fake watchdog. Never opens the real socket."""
import logging
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
from multiprocessing.connection import Listener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge import WatchdogClient, worker
from control_core import Config, Control, ARMED, FAULT


def main():
    with tempfile.TemporaryDirectory(prefix="motorpi-ipc-test-") as folder:
        address = str(Path(folder) / "fake.sock")
        listener = Listener(address, family="AF_UNIX")
        commands = []
        fail = threading.Event()

        def fake_watchdog():
            with listener.accept() as conn:
                try:
                    while True:
                        command = conn.recv(); commands.append(command)
                        if command.startswith("status"):
                            conn.send("OK ret=0 sys_error=%d" % (-65 if fail.is_set() else 0))
                        elif command.startswith("current"):
                            conn.send("OK ret=0 val1=0.05 val2=0.08")
                        else:
                            conn.send("OK")
                except EOFError:
                    commands.append("DISCONNECTED")

        fake = threading.Thread(target=fake_watchdog, daemon=True); fake.start()
        config = Config("00" * 16, live=True, mapping_verified=True,
                        left_dir="cw", right_dir="ccw", socket_path=address)
        control = Control(config, time.monotonic)
        lock, shutdown = threading.Lock(), threading.Event()
        engine = threading.Thread(target=worker, args=(control, lock, shutdown, logging.getLogger("test")))
        engine.start()
        deadline = time.monotonic() + 3
        while not control.ready and time.monotonic() < deadline:
            time.sleep(.02)
        assert control.ready, "Bridge did not connect to fake watchdog"
        with lock:
            control.state = ARMED; control.last_input = time.monotonic(); control.target = (700, -700)
        time.sleep(.25)
        assert "speed 0 700" in commands and "speed 1 -700" in commands, commands
        fail.set()
        engine.join(timeout=2); fake.join(timeout=1); listener.close()
        assert control.state == FAULT and "DISCONNECTED" in commands, commands
        assert commands[-1] == "DISCONNECTED"
        print("PASS: real Unix IPC to private fake watchdog, both motor commands and fault disconnect")


if __name__ == "__main__":
    main()
