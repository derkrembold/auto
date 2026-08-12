# currentsensor — Context for Claude Code

This folder holds reference material for the planned current-sensor LIN
slave — see root `CLAUDE.md`'s LIN Protocol "Slave Topology" section
("2 motor slaves, 1 current sensor, 1 light sensor" planned expansion).
See also `raspi/watchdog/CLAUDE.md`, which polls this sensor (1×/second
— matches the sensor's own ~1s on-board averaging window, see Hardware
below; an earlier "~4×/second" plan predated actually knowing that and
is now outdated) as a secondary, currently observe-only overcurrent
safety net.

## Notes Origin

`notes.md` is findings from a university course project (DCPS — Design
of Cyber-Physical Systems, Semester 5) where students built and debugged
a LIN-based current sensor. Kept as reference/background for building
this project's own current-sensor slave, not as this project's own
build log — the course project's system (Raspi master + 4 ATmega328P
slaves, one per wheel) is a different, unrelated vehicle, not this
project's motor setup.

Genuinely useful findings in there include:
- **Problem 9** documents the exact write/read-echo requirement on the
  Raspi's LIN transceiver (write a byte, must read back and discard the
  echo, or it corrupts the next read) — the same issue independently
  found and fixed in this project's `raspi/control/motorcontrol.py`
  (see `raspi/CLAUDE.md`'s LIN Protocol Timing section). Good
  corroboration that the fix is correct.
- **Problem 8** and **Problem 10** cover LIN address table (`pids`,
  `sources`, `destinations`, `messagebytes`) consistency bugs between
  the C++/slave side and the Python/Raspi side — directly relevant to
  keeping `linaddresses.py` and `addresses.h` in sync (see root
  `CLAUDE.md`'s LIN Protocol section).

**`notes.md` is a living document** — not a frozen snapshot of the DCPS
findings, it may be updated (e.g. once this project's own current-sensor
hardware/firmware work starts and produces its own findings).

## Hardware

The board carries **two ACS712xLCTR-20A** Hall-effect current-sensing
chips — one channel per physical motor, so a single current-sensor board
can measure current for up to 2 motors at once (matches the "up to 4
motors, 2 current sensors" reserved capacity in root `CLAUDE.md`'s LIN
Protocol section, at 2 motors per sensor board). Each ACS712's analog
output feeds one of the ATmega328's ADC inputs (`readadc(2)`/`readadc(3)`
in `firmware/main.cpp`), 10-bit resolution. At 0 A, the raw ADC reading
sits at the midpoint, **~512** (matches the ACS712's own output biasing
at `Vcc/2`, before this project's `Lin`-side scaling was ever attempted).
`st0cur`'s 4-byte reply packs both readings — `val1` = ACS712 #1 (channel
2), `val2` = ACS712 #2 (channel 3), sent as raw 10-bit counts (0-1023)
over LIN. **Conversion to amps happens on the Raspi side**
(`raspi/watchdog/linbus.py`'s `_adc_to_amps()`), not on the AVR —
deliberate: the ATmega328 has no FPU, the calibration may still need
tuning (easier to adjust in Python than to reflash), and `get_temp()`
already follows the same raw-on-the-wire/converted-on-the-master
pattern. Confirmed constants: `Vcc` = 5V (ATmega328 AVCC reference,
also the ACS712 supply), 2.5V = 0A (confirmed against real hardware —
raw reads ~512 at 0A), 100 mV/A sensitivity (ACS712xLCTR-**20A**
datasheet value — the 20A variant, not the 5A/30A ones, which have
different sensitivities).

KiCad design for this board: `C:\Users\rembo\Documents\KiCad\designs\
Abgabe Stromsensor\Abgabe Stromsensor\Current Sensor Board` — a
different KiCad project from the STM32 `demoboard` PCB referenced in
`STM32/CLAUDE.md` (unrelated boards, don't confuse the two "boards
with schematics" in this repo's toolchain).

## Firmware

`firmware/` holds the DCPS course project's current-sensor ATmega328P
source (`main.cpp`, `addresses.h`, `errors.hpp`, `Makefile` — `.hpp` was
renamed to `.h`, see root `CLAUDE.md`'s LIN Protocol section on why)
— starting point for this project's own current-sensor slave (still has
the original author's LIN addressing in `addresses.h`, see Open Points).
Only source files were copied — build artifacts (`.o`/`.s`/`.ii`/`.elf`/
`.hex`) and editor backups (`~` files) were intentionally left out (and
are `.gitignore`d, so `make` output never needs manual cleanup before a
commit).

**Build: working (2026-08-05).** `current.elf`/`current.hex` build from
this folder's own `Makefile` (sibling to `firmware/`, calls `cd firmware
&& make -f Makefile objects` then links + `avr-objcopy`s to `.hex`) —
same toolchain (`avr-gcc`, bundled `make-3.81`) as `STM32/build.sh`
uses, just AVR instead of ARM. Chosen deliberately as a **standalone
copy** (option 1 of two discussed), not a live reference into
`C:\Users\rembo\Documents\ATMEGA328\Controller\` (the original DCPS
project's shared multi-target build, which builds `current`/`light`/
`eeprom`/4×`slave` all from common `cores`/`common`/`client` object
trees) — same reasoning as the STM32 `demoboard` correction: avoid
drift risk between a copy and a hand-maintained original. Turned out to
be straightforward: `main.cpp` doesn't call into the Arduino
Wiring/HardwareSerial layer at all (raw AVR port/ADC access, own
`transmitbyte`/`receivebyte`), so `CORE_OBJECTS` (the `cores/arduino/*.o`
the original Controller Makefile links in) isn't needed here — no
missing-dependency risk from going standalone.

**Protocol fix, same day:** the slave→master (`stslv2`-equivalent) reply
path used to send a hardcoded `0xFF` as its final "checksum" byte
instead of computing one, and didn't check the echoed bytes at all. Both
fixed: a real `checksum()` (sum-with-wraparound-at-0xFF, then `~sum &
0xFF` — same algorithm as `raspi/watchdog/linbus.py`'s `Lin.checksum()`)
is now computed and sent, and every echoed byte (data and checksum) is
compared against what was sent, erroring (`LIN_CHK_ERR`) on mismatch.
The master→slave (`cntlslv0`-equivalent) handler also now verifies the
received checksum the same way. **`lightsensor/firmware/main.cpp` has
not received the equivalent fix yet** — see `lightsensor/CLAUDE.md`.

Developing/building doesn't *need* to happen on this machine — the repo
is the source-of-truth copy (same pattern as `raspi/control/`) — but as
of the above, it also works fine here if that's convenient.

## Status

Firmware builds cleanly (`current.hex`, reproducible clean rebuild) and
has been flashed to real current-sensor hardware (flashing is always
done manually by the user, not from this repo/Claude — see
`currentsensor/Makefile`'s Firmware section above). Adapted to this
project's own LIN addressing (`st0cur`/`cntl0cur`, correct byte counts
via `generate_addresses.py`'s output) — no longer the DCPS course
project's own addressing.

**Bugs found and fixed on real hardware, 2026-08-06/07:**
- Dispatch used the wrong device's PIDs (`st0lig`/`cntl0lig` instead of
  its own `st0cur`/`cntl0cur`) — fixed.
- The "unknown pid → skip N bytes" fallback path used `getindex()`'s
  return value (an array *index*) as if it were the message's *byte
  count* — fixed to look up `messagebytes[index]`.
- Sync-byte detection called the blocking, LED-blinking `error()` on
  every mismatch (up to ~4.5s per call) — since the bus is busy (the
  watchdog self-polls `rpm` every second), this reliably cascaded into
  repeated, self-perpetuating desync ("aus dem Tritt"), which a plain
  reset couldn't fix (the master never paused long enough for the
  sensor's own blocking delays to line up with a real gap). Fixed by
  scanning for `sync` in a tight, non-blocking loop instead.
- The `st0cur` reply loop's echo-mismatch handling used `continue`
  inside the byte-send `for` loop (only skips to the next byte) instead
  of aborting the whole reply — fixed with an `aborted` flag + `break`.

**Confirmed working on the real shared LIN bus together with the motor
(2026-08-07):** `raspi/control/validate_motor_currentsensor.py` (motor
speed steps interleaved with `current`/`hal`/`rpm` queries — see its own
module docstring) ran clean end-to-end. This was also the scenario that
originally exposed a matching STM32-side bug (`HAL_UART_RxCpltCallback`
not re-arming UART reception for a recognized-but-foreign pid) — see
`STM32/CLAUDE.md`.

## Open Points (currentsensor-specific)

- **Bus-hang investigation (2026-08-11), continuing next session** — see
  `STM32/CLAUDE.md`'s Open Points for the full writeup (real hardware
  trace caught the STM32 going silent on both `rpm` and `current` reads
  mid-`validate_speed.py`-run). Leading hypothesis: the `st0cur` reply
  loop's `aborted`/`break` echo-check logic (`main.cpp`) sends fewer
  bytes than the STM32 expects when it fires, and the STM32 has no
  timeout waiting for the rest — possibly triggered by the new ~5ms
  Timer1 ISR (added this week for ADC averaging) introducing timing
  jitter into the still-polling-based `receivebyte()`/`transmitbyte()`.
  Unconfirmed — no visibility yet into whether/how often this actually
  fires. Next step planned: an error counter (ideally per error type —
  `LIN_SYN_ERR`/`LIN_CHK_ERR`/`LIN_IND_ERR`/`LIN_NUM_ERR`, or at least
  the `st0cur`-echo-abort case specifically), queryable via a new
  status message (free block at `0x28`, see `addresses.md`). Pairs with
  a similar timeout-counter planned for the STM32 side — together
  they'd show whether the two events actually correlate.
- No hardware instance-strap-pin reading yet (unlike the motor's
  `hwbits`, see `STM32/CLAUDE.md`'s Instance-Selection Jumper section) —
  always answers as instance 0. Fine while only one physical current
  sensor exists; revisit if/when a second one joins the bus.
  `raspi/watchdog/linbus.py`'s `CURRENT_INSTANCE_ID` documents this too.
- ACS712 zero-point (2.5V) is confirmed against real hardware, but the
  "near 0A" noise tolerance is still just an initial guess, not
  characterized — `raspi/watchdog/watchdog.py`'s `CURRENT_STALL_THRESHOLD`
  (0.15A) was chosen with headroom above the ~0.05-0.09A chip-to-chip
  offset observed once, not from a proper noise-floor measurement.
  `validate_motor_currentsensor.py` also still only sanity-bounds the
  raw range, doesn't assert values are close to 0A when the motor is
  stopped.
- Chip-to-chip offset/gain tolerance between the two ACS712s (~0.05-0.09A
  observed with the same real current flowing through both, see Hardware
  above) — no per-channel calibration exists, both use the same fixed
  constants. Deliberately left alone for now (small relative to
  `CURRENT_STALL_THRESHOLD`).
- Apply the same checksum/echo-compare and sync-scan-loop fixes to
  `lightsensor/firmware/main.cpp` — not done yet, see
  `lightsensor/CLAUDE.md`.

Fill these in here once fixed, not in the root `CLAUDE.md`.
