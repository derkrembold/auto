"""One explicitly consented wheel identification run; dry-run by default.

Starts the existing watchdog for this bounded session only, then stops it.
Positive 600 RPM for one second identifies a wheel and its forward sign.
The other wheel remains at zero. No reset/recovery is performed after faults.
"""
import argparse
from pathlib import Path
import signal
import subprocess
import sys
import time

from bridge import WatchdogClient
from control_core import Config


def run_test(client, motor, sleep=time.sleep):
    values = [0, 0]

    def checked_speed(speed):
        for instance in (0, 1):
            client.check_status(instance)
        client.check_current()
        values[motor] = speed
        client.speeds(values)

    checked_speed(0)
    print('MOTOR %d: POSITIVE 600 RPM, one second' % motor, flush=True)
    for _ in range(10):
        checked_speed(600)
        sleep(.1)
    print(client.command('rpm %d' % motor), flush=True)
    print('RAMP DOWN BOTH WHEELS', flush=True)
    for speed in (480, 360, 240, 120, 0):
        checked_speed(speed)
        sleep(.2)
    print('DONE: both setpoints zero', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--motor', type=int, choices=(0, 1), required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--consent', help='After immediate human permission: MOTOR0 or MOTOR1')
    args = parser.parse_args()
    if not args.live:
        print('DRY RUN: motor %d +600 RPM for one second, one-second ramp; other motor zero.' % args.motor)
        return
    if args.consent != 'MOTOR%d' % args.motor:
        parser.error('Live wheel test needs immediate human consent for this motor')
    directory = Path(__file__).resolve().parent.parent
    if Path('/tmp/motorwatchdog.sock').exists():
        parser.error('Another watchdog session exists; refusing to take over')
    # A SIGTERM closes IPC in finally, invoking the existing stop-all behavior.
    def interrupted(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    client = WatchdogClient(Config('00' * 16))
    watchdog = subprocess.Popen([sys.executable, str(directory / 'watchdog.py'), '--live'],
                                cwd=str(directory))
    owned_socket = None
    try:
        deadline = time.monotonic() + 8
        while not Path(client.config.socket_path).exists():
            if watchdog.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Watchdog did not start')
            time.sleep(.1)
        owned_socket = Path(client.config.socket_path).stat().st_ino
        client.connect()
        run_test(client, args.motor)
    finally:
        client.close()
        time.sleep(.3)
        watchdog.terminate()
        try:
            watchdog.wait(timeout=3)
        except subprocess.TimeoutExpired:
            watchdog.kill()
            watchdog.wait()
        # SIGTERM does not run Listener's Python atexit socket cleanup.
        socket_path = Path(client.config.socket_path)
        if owned_socket is not None and socket_path.exists() and socket_path.stat().st_ino == owned_socket:
            socket_path.unlink()


if __name__ == '__main__':
    main()
