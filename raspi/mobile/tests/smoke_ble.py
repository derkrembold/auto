"""Real BLE transport check against SIMULATION ONLY. Requires bleak on the test laptop."""
import argparse
import asyncio
import hashlib
import hmac
from pathlib import Path
import struct
import sys

from bleak import BleakClient, BleakScanner
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_core import CHALLENGE_UUID, COMMAND_UUID, STATUS_UUID
from access_code import derive_key


async def check(address, credentials):
    text = Path(credentials).read_text()
    code = next(line.split(": ", 1)[1] for line in text.splitlines()
                if line.startswith("MotorPi Bluetooth access code:"))
    key = derive_key(code) if len(code) == 8 else bytes.fromhex(code)
    device = await BleakScanner.find_device_by_address(address, timeout=15)
    if device is None:
        raise RuntimeError("MotorPi not discovered over Bluetooth")
    async with BleakClient(device, timeout=15) as client:
        status = bytes(await client.read_gatt_char(STATUS_UUID))
        if len(status) != 20 or status[2] & 1:
            raise RuntimeError("Refusing test: endpoint is not a recognized SIMULATION service")
        nonce = bytes(await client.read_gatt_char(CHALLENGE_UUID))
        notifications = []
        await client.start_notify(STATUS_UUID, lambda _, data: notifications.append(bytes(data)))

        async def until(predicate, description, timeout=3):
            deadline = asyncio.get_running_loop().time() + timeout
            while not predicate():
                if asyncio.get_running_loop().time() > deadline:
                    raise AssertionError(description)
                await asyncio.sleep(.01)

        # Match Android's serialized handshake: discovery/read, then CCC setup,
        # then authentication, with notification confirmation from the Pi.
        await until(lambda: bool(notifications), "Status channel not ready")
        auth = b"\x00" + hmac.new(key, b"auth" + nonce, hashlib.sha256).digest()[:16]
        invalid = auth[:-1] + bytes([auth[-1] ^ 1])
        await client.write_gatt_char(COMMAND_UUID, invalid, response=False)
        rejected = bytes(await client.read_gatt_char(STATUS_UUID))
        assert not rejected[2] & 2, "Invalid access code was accepted"
        await client.write_gatt_char(COMMAND_UUID, auth, response=False)
        await until(lambda: any(data[2] & 2 for data in notifications), "Authentication not confirmed")
        sequence = 0

        async def send(op, forward=0, steer=0, held=False):
            nonlocal sequence
            sequence += 1
            flags = (128 if held else 0) | 60 if op == 2 else 0
            body = struct.pack("<BIhhB", op, sequence, forward, steer, flags)
            tag = hmac.new(key, nonce + body, hashlib.sha256).digest()[:10]
            await client.write_gatt_char(COMMAND_UUID, body + tag, response=False)
            deadline = asyncio.get_running_loop().time() + .5
            while not any(struct.unpack_from("<I", data, 8)[0] == sequence for data in notifications):
                if asyncio.get_running_loop().time() > deadline:
                    raise AssertionError("Pi did not acknowledge sequence %d" % sequence)
                await asyncio.sleep(.01)

        await send(1)
        for _ in range(4):
            await send(2, 1000, 0, True)
            await asyncio.sleep(.12)
        status = bytes(await client.read_gatt_char(STATUS_UUID))
        assert struct.unpack_from("<hh", status, 4) == (720, 720), status.hex()
        await send(3)
        await asyncio.sleep(1.3)
        status = bytes(await client.read_gatt_char(STATUS_UUID))
        assert status[1] == 0 and struct.unpack_from("<hh", status, 4) == (0, 0), status.hex()
        await send(1)
        await send(2, 1000, 0, True)
        await asyncio.sleep(2)
        status = bytes(await client.read_gatt_char(STATUS_UUID))
        assert status[1] == 0 and status[3] == 1, status.hex()
        assert notifications, "No BLE status notifications received"
        await send(1)
        await send(2, 1000, 0, True)
        await asyncio.sleep(.15)
        await client.stop_notify(STATUS_UUID)
        print("PASS: real BLE discovery/authentication/20-byte commands/status notifications")
        print("PASS: simulated dual-motor drive, staged Stop, heartbeat-loss stop")
    # WinRT may keep the physical link briefly after closing its GATT session.
    await asyncio.sleep(5)
    async with BleakClient(device, timeout=15) as client:
        status = bytes(await client.read_gatt_char(STATUS_UUID))
        assert status[1] == 0 and struct.unpack_from("<hh", status, 4) == (0, 0), status.hex()
        assert not status[2] & 2, "Disconnected peer retained ownership"
        print("PASS: physical BLE disconnect revokes ownership and stops both simulated motors")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", required=True)
    parser.add_argument("--credentials", required=True)
    args = parser.parse_args()
    asyncio.run(check(args.address, args.credentials))
