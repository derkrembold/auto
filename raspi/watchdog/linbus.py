import struct

from linaddresses import constants

SLP_PIN = 23  # enables the LIN transceiver
UART_PORT = '/dev/ttyS0'
UART_BAUDRATE = 19200

SPEED_MIN = -32768
SPEED_MAX = 32767


def hexbyte(value):
    return f"0x{value & 0xFF:02x}"


def hexword(value):
    # 16-bit two's-complement representation, so a negative signed value
    # (e.g. rpm) shows the actual on-wire bit pattern, not a Python
    # minus-sign notation that doesn't correspond to any wire byte.
    return f"0x{value & 0xFFFF:04x}"


class Lin:

    def __init__(self):
        # Imported here, not at module level, so this module (and its
        # pure-logic staticmethods below) stays importable/testable on
        # machines without RPi.GPIO/pyserial — only instantiating Lin()
        # for real needs actual Pi hardware.
        import serial
        import RPi.GPIO as GPIO
        self._gpio = GPIO

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

    @staticmethod
    def checksum(data):
        check = 0
        for abyte in data:
            check += abyte
            if check > 0xFF:
                check -= 0xFF
        return (~check) & 0xFF

    @staticmethod
    def addparity(pid):
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
            read_desc = hexbyte(echo[0]) if echo else 'nothing'
            print(f"echo mismatch: wrote {hexbyte(byte_value)}, "
                  f"read {read_desc}")
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
        self._gpio.cleanup()


class DryRunLin:
    # Stand-in for Lin with the same write()/read() interface, used when
    # the watchdog is not started with --live. Never touches serial or
    # GPIO. Prints every command for a human to watch, and records it
    # (self.writes) for tests to assert against — see
    # raspi/watchdog/CLAUDE.md's "Dry-Run Mode" section.

    def __init__(self):
        self.writes = []
        # address -> list of bytes; test-injected fake read responses.
        # Defaults to zero-filled data of the right length if unset.
        self.read_responses = {}

    def write(self, address, data):
        data = list(data)
        self.writes.append((address, data))

        print(f"[dry-run] write sync      = {hexbyte(constants.sync)}")
        print(f"[dry-run] write address   = {hexbyte(Lin.addparity(address))}"
              f"  (pid {hexbyte(address)})")
        for b in data:
            print(f"[dry-run] write data      = {hexbyte(b)}")
        print(f"[dry-run] write checksum  = {hexbyte(Lin.checksum(data))}")
        print()
        return 0

    def read(self, address):
        if address in self.read_responses:
            data = self.read_responses[address]
        else:
            index = constants.pids.index(address)
            data = [0] * constants.messagebytes[index]

        print(f"[dry-run] read  sync      = {hexbyte(constants.sync)}")
        print(f"[dry-run] read  address   = {hexbyte(Lin.addparity(address))}"
              f"  (pid {hexbyte(address)})")
        for b in data:
            print(f"[dry-run] read  data      = {hexbyte(b)}")
        print(f"[dry-run] read  checksum  = {hexbyte(Lin.checksum(data))}")
        print()
        return 0, data

    def close(self):
        pass


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
