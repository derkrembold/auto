"""Run one consented real-driving session, restoring simulation on exit.

No live autostart or restart. App Start is required after every stop or reconnect.
"""
import argparse
import json
from pathlib import Path
import signal
import subprocess
import sys
import time

from control_core import Config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='/etc/motorpi-mobile/config.json')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--consent', help='Immediate human session consent: STARTFAHRT')
    args = parser.parse_args()
    if not args.live:
        print('DRY RUN: no services changed, no motor commands sent')
        return
    if args.consent != 'STARTFAHRT':
        parser.error('Immediate human consent is required for this driving session')
    data = json.loads(Path(args.config).read_text())
    for key in ('listen_host', 'listen_port'):
        data.pop(key, None)
    config = Config(**data)
    if not config.live:
        parser.error('Verified live configuration required')
    socket_path = Path(config.socket_path)
    if socket_path.exists():
        parser.error('Existing watchdog session; refusing to take over')
    directory = Path(__file__).resolve().parent
    watchdog = server = None
    owned_socket = None
    def interrupted(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        subprocess.run(['sudo', '-n', 'systemctl', 'stop', 'motorpi-mobile'], check=True)
        watchdog = subprocess.Popen([sys.executable, str(directory.parent / 'watchdog.py'), '--live'],
                                    cwd=str(directory.parent))
        deadline = time.monotonic() + 8
        while not socket_path.exists():
            if watchdog.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Live watchdog did not start')
            time.sleep(.1)
        owned_socket = socket_path.stat().st_ino
        server = subprocess.Popen([sys.executable, str(directory / 'wifi_server.py'),
                                   '--config', args.config, '--live'], cwd=str(directory))
        print('Live session running: authenticate in the app, then press START.', flush=True)
        while watchdog.poll() is None and server.poll() is None:
            time.sleep(.2)
        raise RuntimeError('Live process exited; ending the driving session')
    finally:
        # Server SIGTERM performs the existing proportional ramp before closing IPC.
        for process, wait_s in ((server, 5), (watchdog, 3)):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=wait_s)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if owned_socket is not None and socket_path.exists() and socket_path.stat().st_ino == owned_socket:
            socket_path.unlink()
        subprocess.run(['sudo', '-n', 'systemctl', 'start', 'motorpi-mobile'], check=True)


if __name__ == '__main__':
    main()
