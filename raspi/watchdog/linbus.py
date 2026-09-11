import logging
import struct
import threading

from linaddresses import constants

# Child of the "watchdog" logger configured in watchdog.py's serve() --
# propagates to its handlers automatically (file always gets everything
# at DEBUG, terminal only if --debug), no separate setup needed here.
# See raspi/watchdog/CLAUDE.md's log-format notes.
logger = logging.getLogger("watchdog.linbus")

SLP_PIN = 23  # enables the LIN transceiver
UART_PORT = '/dev/ttyS0'
UART_BAUDRATE = 19200

SPEED_MIN = -32768
SPEED_MAX = 32767

# Multi-instance addressing (2026-09-11): every motor/current-sensor
# command below now takes an explicit `instance` argument -- no more
# single hardcoded module-level target. The actual on-wire pid is
# base_pid | constants.<class>_instances[instance], resolved per-call by
# _motor_wire_id()/_current_wire_id() below. This mirrors the firmware's
# own PB14/PB15 strap-pin scheme (see STM32/CLAUDE.md's
# "Instance-Selection Jumper" section) exactly: instance 0 = both pins
# grounded, instance 1 = PB14 grounded/PB15 not, etc.
#
# IMPORTANT PHYSICAL PRECONDITION: a board with *neither* jumper set
# reads hwbits = 0x03 (both PB14/PB15 float HIGH via internal pull-ups)
# -- instance 3, not 0. The one real motor on the bus before this change
# was never jumpered (only one motor existed, no instance selection
# needed) and so answers as instance 3 today. For it to be reachable as
# "motor 0" under this new addressing (and for the watchdog's own
# self-polling/stall-check/overcurrent-stop, which now targets a fixed
# MONITORED_MOTOR_INSTANCE, see watchdog.py), its jumper must actually be
# set to ground both PB14 and PB15. Until that's done, `speed 0 500`
# etc. against the real motor will just time out (no reply) -- this is a
# hardware step, not a code gap.
def _motor_wire_id(instance):
    # Resolves a motor instance number (0-3) to its strap-pin wire id.
    # Range is validated upstream (watchdog.py's validate(), see
    # MOTOR_INSTANCE_MIN/MAX) -- a bad instance here raises KeyError as a
    # defensive backstop, not the primary check, same pattern as
    # set_pi()'s clamp below.
    return constants.motor_instances[instance]


def _current_wire_id(instance):
    # Resolves a current-sensor instance number (0-1) to its wire id.
    # Same defensive-backstop reasoning as _motor_wire_id() above --
    # watchdog.py's validate() is the primary range check.
    return constants.current_instances[instance]

# ACS712xLCTR-20A conversion (see currentsensor/CLAUDE.md's Hardware
# section) -- done here, not on the AVR, deliberately: the ATmega328 has
# no FPU (float math would mean slow/large software emulation on the
# sensor), the calibration constants may still need tuning, and
# `get_temp()` below already sends its ADC reading raw and converts on
# this side -- same precedent.
ADC_VCC = 5.0  # volts, ATmega328 AVCC reference (also the ACS712 supply)
ADC_STEPS = 1024  # 10-bit ADC -> raw counts 0-1023
ACS712_ZERO_VOLTAGE = 2.5  # volts at 0 A -- confirmed against real hardware (raw=512)
ACS712_SENSITIVITY = 0.100  # V/A, ACS712xLCTR-20A datasheet value


def _adc_to_amps(raw):
    voltage = raw * ADC_VCC / ADC_STEPS
    return (voltage - ACS712_ZERO_VOLTAGE) / ACS712_SENSITIVITY


def hexbyte(value):
    return f"0x{value & 0xFF:02x}"


def hexword(value):
    # 16-bit two's-complement representation, so a negative signed value
    # (e.g. rpm) shows the actual on-wire bit pattern, not a Python
    # minus-sign notation that doesn't correspond to any wire byte.
    return f"0x{value & 0xFFFF:04x}"


def _log_source():
    # Which thread triggered this bus call: Watchdog.monitor() runs in
    # its own background thread (self-polling); Watchdog.execute() (via
    # serve()'s accept loop) runs on the main thread (client commands).
    # Auto-detected from the thread itself rather than threaded through
    # every call site as a parameter.
    if threading.current_thread() is threading.main_thread():
        return "[client]"
    return "[poll]  "


def _log_pid_name(address):
    return constants.pid_names.get(address, hexbyte(address))


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
            logger.warning(f"echo mismatch: wrote {hexbyte(byte_value)}, "
                            f"read {read_desc}")
            return False
        return True

    def write(self, address, data, instance=0x00):
        # `address` is a message's BASE pid (from constants.pids) -- used
        # as-is to look up byte count/source, but combined with `instance`
        # (the target unit's strap-pin id, e.g. constants.motor_instances[n])
        # for what actually goes out on the wire. See _motor_wire_id()/
        # _current_wire_id() below for how callers resolve that.
        if address not in constants.pids:
            logger.warning("pid not known")
            return -1
        index = constants.pids.index(address)
        mbytes = constants.messagebytes[index]
        if len(data) != mbytes:
            logger.warning("number of bytes wrong")
            return -2
        if constants.sources[index] != "master":
            logger.warning("you must be master to write")
            return -3

        wire_pid = address | instance

        # No matching "<-" line by design: a LIN write gets no slave
        # reply (see raspi/watchdog/CLAUDE.md's log-format notes) -- a
        # write's own local echo-check outcome isn't logged here, only
        # that it started, matching the one-line-per-write shape agreed
        # on with the user. Always logged at DEBUG -- the file handler
        # captures it unconditionally, only the terminal echo depends on
        # --debug (see watchdog.py's logging setup).
        data_str = [hexbyte(b) for b in data]
        logger.debug(f"{_log_source()}  -> write {_log_pid_name(address):<10}"
                      f" data={data_str}")

        if not self.write_byte(constants.sync):
            return -4
        if not self.write_byte(self.addparity(wire_pid)):
            return -4

        for b in data:
            if not self.write_byte(b):
                return -4

        if not self.write_byte(self.checksum(data)):
            return -4

        return 0

    def read(self, address, instance=0x00):
        # See write() above for base-pid-vs-wire-pid/instance reasoning.
        if address not in constants.pids:
            logger.warning("pid not known")
            return -1, []
        index = constants.pids.index(address)
        mbytes = constants.messagebytes[index]
        if constants.sources[index] == "master":
            logger.warning("you must be client to write")
            return -2, []

        wire_pid = address | instance
        name = _log_pid_name(address)

        logger.debug(f"{_log_source()}  -> read  {name:<10}")

        def _finish(ret, data):
            data_str = [hexbyte(b) for b in data]
            logger.debug(f"{_log_source()}  <- read  {name:<10}"
                         f" ret={ret}  data={data_str}")
            return ret, data

        if not self.write_byte(constants.sync):
            return _finish(-4, [])
        if not self.write_byte(self.addparity(wire_pid)):
            return _finish(-4, [])

        data = []
        for _ in range(mbytes):
            response = self.ser.read(1)
            if len(response) != 1:
                logger.warning("no response from slave (read timeout)")
                return _finish(-5, data)
            data.append(response[0])

        response = self.ser.read(1)
        if len(response) != 1:
            logger.warning("no response from slave (checksum read timeout)")
            return _finish(-5, data)
        if response[0] != self.checksum(data):
            logger.warning("checksum not right")
            return _finish(-3, data)

        return _finish(0, data)

    def write_bad_checksum(self, address, data, instance=0x00):
        # Same as write() but deliberately sends a wrong checksum byte
        # (bitwise complement of the correct one -- guaranteed different).
        # Exists only to test STM32/firmware/Core/Src/main.c's
        # checksum_ok gate on the cntl*mot dispatch actually rejects a
        # corrupted master write on real hardware -- every operational
        # caller must use write() instead.
        if address not in constants.pids:
            logger.warning("pid not known")
            return -1
        index = constants.pids.index(address)
        mbytes = constants.messagebytes[index]
        if len(data) != mbytes:
            logger.warning("number of bytes wrong")
            return -2
        if constants.sources[index] != "master":
            logger.warning("you must be master to write")
            return -3

        wire_pid = address | instance
        bad_checksum = self.checksum(data) ^ 0xFF

        data_str = [hexbyte(b) for b in data]
        logger.debug(f"{_log_source()}  -> write {_log_pid_name(address):<10}"
                      f" data={data_str} (DELIBERATELY BAD CHECKSUM)")

        if not self.write_byte(constants.sync):
            return -4
        if not self.write_byte(self.addparity(wire_pid)):
            return -4

        for b in data:
            if not self.write_byte(b):
                return -4

        if not self.write_byte(bad_checksum):
            return -4

        return 0

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

    def write(self, address, data, instance=0x00):
        data = list(data)
        wire_pid = address | instance
        self.writes.append((wire_pid, data))

        print(f"[dry-run] write sync      = {hexbyte(constants.sync)}")
        print(f"[dry-run] write address   = {hexbyte(Lin.addparity(wire_pid))}"
              f"  (pid {hexbyte(wire_pid)})")
        for b in data:
            print(f"[dry-run] write data      = {hexbyte(b)}")
        print(f"[dry-run] write checksum  = {hexbyte(Lin.checksum(data))}")
        print()
        return 0

    def read(self, address, instance=0x00):
        # Keyed by the base address, not the wire pid -- tests inject
        # responses per message type, independent of which instance a
        # call happens to target. See Lin.write()'s docstring comment.
        wire_pid = address | instance
        if address in self.read_responses:
            data = self.read_responses[address]
        else:
            index = constants.pids.index(address)
            data = [0] * constants.messagebytes[index]

        print(f"[dry-run] read  sync      = {hexbyte(constants.sync)}")
        print(f"[dry-run] read  address   = {hexbyte(Lin.addparity(wire_pid))}"
              f"  (pid {hexbyte(wire_pid)})")
        for b in data:
            print(f"[dry-run] read  data      = {hexbyte(b)}")
        print(f"[dry-run] read  checksum  = {hexbyte(Lin.checksum(data))}")
        print()
        return 0, data

    def write_bad_checksum(self, address, data, instance=0x00):
        # Mirrors write() -- see Lin.write_bad_checksum()'s docstring.
        return self.write(address, data, instance=instance)

    def close(self):
        pass


def set_speed(lin, instance, value):
    # `value` is assumed to be RPM, but this is unconfirmed — the firmware
    # side has never been verified against an actual measured speed. Check
    # this once the Saleae Hall-edge speed measurement is in place.
    value = max(SPEED_MIN, min(SPEED_MAX, int(value)))
    data = struct.pack('>h', value)
    return lin.write(constants.cntl3mot, data, instance=_motor_wire_id(instance))


def set_pulse(lin, instance, value):
    # cntl1mot -- a single raw, open-loop driveStep() pulse (main.c's
    # cntl1mot dispatch), no PI controller/ramp involved at all. Built
    # 2026-08-28 for characterizing torque response by starting Hall
    # position (see analysis/grid_search_log.md's Dead Zone discussion).
    # This module-level clamp is just the wire-format safety backstop
    # (same SPEED_MIN/MAX int16 range set_speed() above clamps to, so
    # struct.pack() below can never overflow) -- the real, much
    # tighter policy range (driveState() silently no-ops once the
    # magnitude reaches GLOBALRATE=1275us rather than clamping or
    # erroring) lives in watchdog.py's PULSE_SPEED_MIN/MAX, checked in
    # validate() before this function is ever called, same two-tier
    # pattern as set_speed()/SPEED_MIN/MAX above.
    value = max(SPEED_MIN, min(SPEED_MAX, int(value)))
    data = struct.pack('>h', value)
    return lin.write(constants.cntl1mot, data, instance=_motor_wire_id(instance))


def set_pi(lin, instance, p_delta, i_delta):
    # cntl0mot's body is two signed bytes (int8_t), each *100 -- the
    # firmware always computes KP = KPDEFAULT + byte/100.0 (never
    # cumulative against whatever KP currently is), so p_delta/i_delta
    # here are absolute deltas from the firmware's hardcoded default,
    # not increments from the last call. See STM32/CLAUDE.md's Motor
    # Control section and raspi/CLAUDE.md's Structure section for the
    # -1.28..1.27 range this maps to. Caller (watchdog.py's validate())
    # is expected to have range-checked already; clamp again here as a
    # defensive backstop against the wire encoding, not the primary
    # check.
    p_byte = max(-128, min(127, round(p_delta * 100)))
    i_byte = max(-128, min(127, round(i_delta * 100)))
    data = struct.pack('bb', p_byte, i_byte)
    return lin.write(constants.cntl0mot, data, instance=_motor_wire_id(instance))


def get_hal(lin, instance):
    return lin.read(constants.st0mot, instance=_motor_wire_id(instance))


def get_rpm(lin, instance):
    ret, data = lin.read(constants.st2mot, instance=_motor_wire_id(instance))
    if ret < 0:
        return ret, None
    raw = data[0] + 256 * data[1]
    if raw >= 0x8000:
        raw -= 0x10000
    return ret, raw


def get_temp(lin, instance):
    ret, data = lin.read(constants.st1mot, instance=_motor_wire_id(instance))
    if ret < 0:
        return ret, None
    return ret, data[0] + 256 * data[1]


def get_motor_counters(lin, instance):
    # 4-byte reply -- STM32/firmware/Core/Src/main.c's fillbody() st3mot
    # case: data[0:2] = bodyTimeoutCount (how many times the
    # HAL_GetTick() bus-hang timeout has fired, see STM32/CLAUDE.md's
    # Status section), little-endian uint16_t.
    # data[2] = checksumErrorCount (how many times a cntl*mot write
    # addressed to this motor instance failed its checksum check --
    # scoped to writes actually addressed to this device, not every
    # checksum mismatch snooped on the shared bus). **Only the low byte
    # since 2026-08-27** (0-255, wraps silently past that -- fine for a
    # rare-event counter) -- data[3] used to be its high byte but was
    # repurposed for kickStartCount (see get_kick_start_count() below,
    # STM32/firmware/Core/Src/main.c's driveKickStart(), experimental/
    # throwaway diagnostic for the kick-start dead-zone/stiction fix).
    # Plain unsigned -- unlike get_error_history()'s codes, these are
    # counters, not two's-complement error codes.
    ret, data = lin.read(constants.st3mot, instance=_motor_wire_id(instance))
    if ret < 0:
        return ret, None, None
    timeout_count = data[0] | (data[1] << 8)
    checksum_error_count = data[2]
    return ret, timeout_count, checksum_error_count


def get_kick_start_count(lin, instance):
    # Experimental/throwaway diagnostic (2026-08-27) for the firmware
    # kick-start mechanism (main.c's driveKickStart()) -- st3mot's
    # data[3], a free-running counter (mod 16 on the firmware side,
    # wraps silently) incremented once per 100ms window the kick fires.
    # Only tells you "did it fire, roughly how often recently" -- not a
    # reliable whole-session total, see root CLAUDE.md/analysis/
    # grid_search_log.md for the kick-start design discussion. Separate
    # function rather than folded into get_motor_counters() so that
    # function's existing callers (selftest()'s checksum/bus-hang
    # provocations) don't need updating for a value they don't care
    # about.
    ret, data = lin.read(constants.st3mot, instance=_motor_wire_id(instance))
    if ret < 0:
        return ret, None
    return ret, data[3]


def reset_motor(lin, instance):
    # cntl2mot, repurposed 2026-09-07 (was a raw per-MOSFET debug write,
    # driveMOSFET() directly -- never actually sent from the Raspi side,
    # see STM32/CLAUDE.md's Planned Redesign section) into a full state
    # reset: the firmware clears controlvariableinput, integral,
    # bodyTimeoutCount, checksumErrorCount, kickStartCount,
    # stuckwindowcount, and sysError (back to MOT_OK) -- see main.c's
    # cntl2mot dispatch. The handler ignores the body content entirely
    # (reset fires purely off the checksum-gated PID match), but the
    # wire format still requires exactly messagebytes[cntl2mot] (6,
    # unchanged from the old MOSFET-control layout -- deliberately left
    # at 6 rather than shrunk, for headroom towards a possible future
    # selective-reset bitmask, see analysis/grid_search_log.md's
    # 2026-09-07 discussion) body bytes + checksum, so 6 zero bytes go
    # out as a harmless placeholder payload.
    return lin.write(constants.cntl2mot, bytes(6), instance=_motor_wire_id(instance))


def get_motor_status(lin, instance):
    # Full 6-byte st3mot reply (extended 2026-09-07 from 4 bytes, see
    # STM32/CLAUDE.md's Planned Redesign section) in one LIN round-trip
    # -- use this instead of separate get_motor_counters()/
    # get_kick_start_count() calls when the full picture is wanted (e.g.
    # confirming reset_motor() actually cleared everything). Those two
    # functions are left as-is for their existing callers (selftest()'s
    # provocation checks only ever cared about the timeout/checksum
    # counts). data[4] = sysError (main.c's MOT_OK=0/STALL_TIM_ERR=-65/
    # etc., from errors.h -- signed, two's-complement, unlike the plain
    # unsigned counters), data[5] = reserved, always 0.
    ret, data = lin.read(constants.st3mot, instance=_motor_wire_id(instance))
    if ret < 0:
        return ret, None, None, None, None
    timeout_count = data[0] | (data[1] << 8)
    checksum_error_count = data[2]
    kickstart_count = data[3]
    sys_error = data[4]
    if sys_error >= 0x80:
        sys_error -= 0x100
    return ret, timeout_count, checksum_error_count, kickstart_count, sys_error


# currentsensor/firmware/main.cpp's storeerror() ring buffer (see
# errors.hpp) -- names for st1cur's raw codes, purely for human-readable
# display (motorcontrol.py's `errors` command). 0 = unused slot/no error.
CURRENTSENSOR_ERROR_NAMES = {
    0: "OK",
    -1: "SYN",
    -2: "PAR",
    -3: "PID",
    -4: "MSI",
    -5: "CHK",
    -6: "TIM",
    -7: "IND",
    -8: "NUM",
}


def get_error_history(lin, instance):
    # 8-byte reply: currentsensor/firmware/main.cpp's errorstorage[8],
    # most recent error first, sent as raw int8_t bytes (two's
    # complement on the wire) -- decoded back to signed ints here, same
    # split-conversion-out-of-the-message-function precedent as
    # get_current()'s _adc_to_amps() above.
    ret, data = lin.read(constants.st1cur, instance=_current_wire_id(instance))
    if ret < 0:
        return ret, None
    codes = [b - 256 if b >= 128 else b for b in data]
    return ret, codes


def currentsensor_selftest(lin, instance):
    # Exercises currentsensor/firmware/main.cpp's cntl0cur test hook end
    # to end: inject a known non-zero pattern into errorstorage (0x01,
    # 0xab), read it back via st1cur, then reset errorstorage to zero
    # (0xcd, 0x0c) and read it back again. Confirms both the write path
    # (cntl0cur) and the read path (st1cur) actually work, independent
    # of whether a real error has ever occurred.
    ret_inject = lin.write(constants.cntl0cur, [0x01, 0xab], instance=_current_wire_id(instance))
    ret_injected, codes_injected = get_error_history(lin, instance)
    ret_reset = lin.write(constants.cntl0cur, [0xcd, 0x0c], instance=_current_wire_id(instance))
    ret_after_reset, codes_after_reset = get_error_history(lin, instance)
    return ret_inject, ret_injected, codes_injected, ret_reset, ret_after_reset, codes_after_reset


def provoke_currentsensor_checksum_error(lin, instance):
    # Deliberately sends currentsensor's cntl0cur "inject test pattern"
    # command ([0x01, 0xab], see currentsensor_selftest() above) with a
    # wrong checksum, to exercise currentsensor/firmware/main.cpp's
    # checksum-gate fix (added 2026-08-15): the checksum is now verified
    # BEFORE any of cntl0cur's three actions run, not after, so this
    # write should be rejected outright.
    #
    # Deliberately uses the *inject* bytes, not e.g. the reset bytes --
    # the reset command's effect (zero everything) is indistinguishable
    # from "errorstorage was already zero", so it wouldn't actually prove
    # the gate did anything. The inject command's fixed non-zero pattern
    # either lands in errorstorage or it doesn't -- caller reads
    # get_error_history() before/after and should see codes[0] == -5
    # (LIN_CHK_ERR, logged unconditionally by error() -- this alone does
    # NOT prove the gate worked, since error() runs on every mismatch
    # regardless) but codes[1] == 0, not 0x11 (proves the inject action
    # itself was actually skipped, not just that a mismatch was noted).
    # Caller should also confirm via get_motor_counters() that the
    # STM32's own checksumErrorCount/bodyTimeoutCount stay unchanged --
    # this message is addressed to the currentsensor (cntl0cur), not the
    # motor, so the STM32's is_our_write scoping should exclude it even
    # though it still tracks the frame on the shared bus.
    data = [0x01, 0xab]
    return lin.write_bad_checksum(constants.cntl0cur, data, instance=_current_wire_id(instance))


def provoke_bus_hang_timeout(lin, instance):
    # Deliberately reproduces, on demand, the short-reply condition that
    # the STM32's HAL_GetTick() bus-hang timeout (main.c) exists to catch
    # (see STM32/CLAUDE.md's Open Points): arms currentsensor's
    # sabotageNextReply (cntl0cur [0xfa,0x17], main.cpp), then triggers a
    # real st0cur read so the sabotage actually fires -- the currentsensor
    # aborts after 1 byte, so this read is expected to time out (ret=-5)
    # on the master's own ~2s pyserial timeout too, same as it would for
    # any other short/missing reply. Caller reads get_motor_counters()/
    # get_error_history() before and after to confirm the STM32 and the
    # currentsensor both actually caught it. Takes ~2s to return (the
    # master's own read timeout on the sabotaged reply) -- expected, not
    # a bug. `instance` here is the currentsensor instance being armed
    # AND read -- the motor instance whose get_motor_counters() the
    # caller separately checks is unrelated to this call.
    ret_arm = lin.write(constants.cntl0cur, [0xfa, 0x17], instance=_current_wire_id(instance))
    ret_trigger, _val1, _val2 = get_current(lin, instance)
    return ret_arm, ret_trigger


def provoke_checksum_error(lin, instance):
    # Deliberately sends a cntl3mot (speed/setpoint) write with a wrong
    # checksum, to exercise STM32/firmware/Core/Src/main.c's checksum_ok
    # gate (added 2026-08-14) on real hardware. Value is fixed at 0 (not
    # some other distinct value) specifically so this stays safe to call
    # without Motor Execution Consent even if the gate turns out to be
    # broken -- a corrupted "speed 0" landing anyway is harmless, unlike
    # a corrupted nonzero value would be. This only proves the STM32
    # *detected* the bad checksum (via checksumErrorCount, see
    # get_motor_counters()) -- it does not by itself prove the motor's
    # setpoint truly didn't change; that needs a direct rpm-based
    # before/after check with a real (nonzero) target speed, which does
    # need Motor Execution Consent and isn't built here yet.
    data = struct.pack('>h', 0)
    return lin.write_bad_checksum(constants.cntl3mot, data, instance=_motor_wire_id(instance))


def get_current(lin, instance):
    # 4-byte reply: 2x 10-bit ADC readings, each split as (low byte,
    # high 2 bits) -- matches currentsensor/firmware/main.cpp's packing
    # (data[0]=val&0xFF, data[1]=(val>>8)&0x03). Converted to amps via
    # _adc_to_amps() -- see its comment for why the conversion lives here
    # and not on the AVR.
    ret, data = lin.read(constants.st0cur, instance=_current_wire_id(instance))
    if ret < 0:
        return ret, None, None
    val1 = _adc_to_amps(data[0] | ((data[1] & 0x03) << 8))
    val2 = _adc_to_amps(data[2] | ((data[3] & 0x03) << 8))
    return ret, val1, val2
