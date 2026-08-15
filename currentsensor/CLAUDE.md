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

**`selftest`'s `cntl0cur` test hook confirmed on real hardware
(2026-08-13)** — see `raspi/CLAUDE.md`'s `motorcontrol.py` entry for what
the command does. `watchdog.log` (fetched and run through
`raspi/analyze_logs.py`) shows two full round trips, both `ret=0`
throughout: `cntl0cur [0x01,0xab]` → `st1cur` reads back the exact
firmware-hardcoded pattern `0x11 55 77 aa bb cc dd ff`, then
`cntl0cur [0xcd,0x0c]` → `st1cur` reads back all zero. Confirms the real
inject-then-reset state transition on the AVR itself, which the
`DryRunLin`-based unit tests in `raspi/tests/test_watchdog.py` can't
exercise (no real firmware state behind the dry-run stub).

**Bus-hang investigation (2026-08-11) — resolved, root cause confirmed
against real hardware (2026-08-13).** See `STM32/CLAUDE.md`'s Status
section for the full STM32-side writeup; this device's role: a
`sabotageNextReply` flag (`main.cpp`, set via a new `cntl0cur`
sub-command `[0xfa,0x17]`) deliberately forces the very first
echo-check of the *next* `st0cur`/`st1cur` reply to fail — reusing the
existing `error(LIN_CHK_ERR)`/`aborted`/`break` path unchanged, so the
real byte-count-short-on-the-wire condition is reproduced faithfully
(not simulated) on demand, self-clearing after one reply.
`raspi/control/motorcontrol.py`'s `selftest` arms this
(`linbus.provoke_bus_hang_timeout()`) and then triggers a real `st0cur`
read. Confirmed three times against real hardware, motor idle twice and
once at commanded speed 500: the sabotaged reply cut off after exactly
1 byte every time (as designed), `errorstorage` logged a fresh `CHK`
entry every time, and the STM32's new timeout (`st3mot`'s
`bodyTimeoutCount`) incremented in lockstep every time — direct,
repeated confirmation that the original hypothesis (this device's own
abort-mid-reply behavior was the trigger) was correct, not just
plausible. The separate currentsensor-side error counter once planned
for this (to correlate against the STM32's counter) turned out
unnecessary — `errorstorage`/`st1cur` already gave that signal.

**`cntl0cur` checksum-gate bug found and fixed (2026-08-15) — same bug
class as the STM32's own checksum fix the day before (see
`STM32/CLAUDE.md`'s Status section).** The checksum byte was read and
compared *after* `cntl0cur`'s three actions (LED on/off, errorstorage
inject, errorstorage reset, sabotage-arm) had already run, not before —
a write with a coincidentally-matching data-byte pattern but a corrupted
checksum would still execute its action, `error(LIN_CHK_ERR)` only got
logged afterward, too late to prevent anything. Fixed by moving the
checksum read+compare to immediately after the two data bytes, `continue`ing
past all three action `if`s on mismatch instead of falling through to
them (`main.cpp`, `cntl0cur` handler).

**Confirmed against real hardware (2026-08-15), same day as built.**
`raspi/control/motorcontrol.py`'s `selftest` gained a new part
(`linbus.provoke_currentsensor_checksum_error()`): sends the *inject*
bytes (`[0x01,0xab]`) with a deliberately wrong checksum via
`Lin.write_bad_checksum()`. Deliberately uses the inject bytes rather
than the reset bytes — reset's effect (zero everything) would be
indistinguishable from "already zero" and wouldn't actually prove the
gate did anything, whereas the inject command's fixed non-zero pattern
either lands in `errorstorage` or it doesn't, making the fix's effect
directly observable. Run twice against real hardware
(`runs/2026-08-15_cs_checksum_test/`): both times `errorstorage[0]`
showed the expected fresh `CHK` entry (`error()` logs a mismatch
unconditionally — this alone would be true with or without the fix) but
critically `errorstorage[1]` stayed `0`, not `0x11` — direct proof the
inject action itself was actually skipped, not just that a mismatch was
noted. Also confirmed via the STM32's `st3mot` counters
(`bodyTimeoutCount`/`checksumErrorCount`, both read before/after) that
the STM32 correctly attributes zero effect to this message — it's
addressed to the currentsensor (`cntl0cur`), not the motor, and even
though the STM32 still tracks the frame going by on the shared bus, its
`is_our_write` scoping correctly excludes it from its own
`checksumErrorCount`. All three of `selftest`'s provocations
(this one, the bus-hang test, and the STM32's own checksum test) moved
only their own counter each time, both runs — confirmed mutually
isolated, not just individually correct.

## Open Points (currentsensor-specific)

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
