import sys
import struct

import serial
import RPi.GPIO as GPIO

from linaddresses import constants

SLP_PIN = 23  # enables the LIN transceiver
UART_PORT = '/dev/ttyS0'
UART_BAUDRATE = 19200

SPEED_MIN = -32768
SPEED_MAX = 32767


class Lin:

    def __init__(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(SLP_PIN, GPIO.OUT)
        GPIO.output(SLP_PIN, GPIO.HIGH)

        self.ser = serial.Serial(
            port=UART_PORT,
            baudrate=UART_BAUDRATE,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
            timeout=2,
        )

    def checksum(self, data):
        check = 0
        for abyte in data:
            check += abyte
            if check > 0xFF:
                check -= 0xFF
        return (~check) & 0xFF

    def addparity(self, pid):
        temp = pid & 0x3F
        p0 = ((pid & 0x01) + ((pid >> 1) & 0x01) + ((pid >> 2) & 0x01) + ((pid >> 4) & 0x01)) & 0x01
        p1 = (~(((pid >> 1) & 0x01) + ((pid >> 3) & 0x01) + ((pid >> 4) & 0x01) + ((pid >> 5) & 0x01))) & 0x01
        temp = (p0 << 6) | temp
        temp = (p1 << 7) | temp
        return temp

    def write_byte(self, byte_value):
        # LIN echoes every transmitted byte back on RX (single-wire bus).
        # The echo must be read AND compared to what we sent, not just
        # discarded, or a bus collision/corruption goes unnoticed.
        self.ser.write(bytes([byte_value]))
        echo = self.ser.read(1)
        if len(echo) != 1 or echo[0] != byte_value:
            print(f"echo mismatch: wrote {hex(byte_value)}, "
                  f"read {echo.hex() if echo else 'nothing'}")
            return False
        return True

    def write(self, address, data):
        if address not in constants.pids:
            print("pid not known")
            return -1
        index = constants.pids.index(address)
        mbytes = constants.messagebytes[index]
        if len(data) != mbytes:
            print("number of bytes wrong")
            return -2
        if constants.sources[index] != constants.master:
            print("you must be master to write")
            return -3

        if not self.write_byte(constants.sync):
            return -4
        if not self.write_byte(self.addparity(address)):
            return -4

        for b in data:
            if not self.write_byte(b):
                return -4

        if not self.write_byte(self.checksum(data)):
            return -4

        return 0

    def read(self, address):
        if address not in constants.pids:
            print("pid not known")
            return -1, []
        index = constants.pids.index(address)
        mbytes = constants.messagebytes[index]
        if constants.sources[index] == constants.master:
            print("you must be client to write")
            return -2, []

        if not self.write_byte(constants.sync):
            return -4, []
        if not self.write_byte(self.addparity(address)):
            return -4, []

        data = []
        for _ in range(mbytes):
            response = self.ser.read(1)
            data.append(response[0])

        response = self.ser.read(1)
        if response[0] != self.checksum(data):
            print("checksum not right")
            return -3, []

        return 0, data

    def close(self):
        self.ser.close()
        GPIO.cleanup()


def set_speed(lin, value):
    # `value` is assumed to be RPM, but this is unconfirmed — the firmware
    # side has never been verified against an actual measured speed. Check
    # this once the Saleae Hall-edge speed measurement is in place.
    value = max(SPEED_MIN, min(SPEED_MAX, int(value)))
    data = struct.pack('>h', value)
    return lin.write(constants.cntlslv3, data)


def led_on(lin):
    # Onboard status LED, not motor power.
    return lin.write(constants.cntlslv0, [0x01, 0xdb])


def led_off(lin):
    return lin.write(constants.cntlslv0, [0xcd, 0x0c])


def get_hal(lin):
    return lin.read(constants.stslv0)


def get_rpm(lin):
    ret, data = lin.read(constants.stslv2)
    if ret < 0:
        return ret, None
    raw = data[0] + 256 * data[1]
    if raw >= 0x8000:
        raw -= 0x10000
    return ret, raw


def get_temp(lin):
    ret, data = lin.read(constants.stslv1)
    if ret < 0:
        return ret, None
    return ret, data[0] + 256 * data[1]


def usage():
    print("Usage:")
    print("  python motorcontrol.py speed <value>   (0 = stop)")
    print("  python motorcontrol.py on              (status LED on)")
    print("  python motorcontrol.py off             (status LED off)")
    print("  python motorcontrol.py hal             (read Hall sensor positions)")
    print("  python motorcontrol.py rpm             (read RPM over LIN)")
    print("  python motorcontrol.py temp            (read temperature)")


def main():
    if len(sys.argv) < 2:
        usage()
        return

    cmd = sys.argv[1]
    lin = Lin()
    try:
        if cmd == "speed":
            if len(sys.argv) < 3:
                usage()
                return
            set_speed(lin, int(sys.argv[2]))
        elif cmd == "on":
            led_on(lin)
        elif cmd == "off":
            led_off(lin)
        elif cmd == "hal":
            ret, data = get_hal(lin)
            print(f"ret={ret} data={[hex(b) for b in data]}")
        elif cmd == "rpm":
            ret, value = get_rpm(lin)
            print(f"ret={ret} rpm={value}")
        elif cmd == "temp":
            ret, value = get_temp(lin)
            print(f"ret={ret} temp={value} (hex={hex(value) if value is not None else None})")
        else:
            usage()
    finally:
        lin.close()


if __name__ == "__main__":
    main()
