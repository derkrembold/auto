# currentsensor — Context for Claude Code

This folder holds reference material for the planned current-sensor LIN
slave — see root `CLAUDE.md`'s LIN Protocol "Slave Topology" section
("2 motor slaves, 1 current sensor, 1 light sensor" planned expansion).
See also `raspi/watchdog/CLAUDE.md`, which plans to poll this sensor
(~4×/second) as a secondary overcurrent safety net.

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

Firmware builds cleanly (`current.hex` produced and verified
reproducible via a clean rebuild, 2026-08-05) with the checksum fix
above. Not yet flashed to real current-sensor hardware, not yet adapted
to this project's own LIN addressing (see Open Points) — still the DCPS
course project's sensor logic otherwise.

## Open Points (currentsensor-specific)

- Replace `firmware/addresses.h` with the real generated one once root
  `CLAUDE.md`'s `addresses.json`/`generate_addresses.py` scheme is
  reviewed and adopted (see its LIN Protocol section) — currently still
  the DCPS course project's own, unrelated addressing.
- Verify/adapt the hardware design this firmware assumes (informed by,
  but not identical to, the DCPS course project's build).
- Flash environment (`avrdude`/programmer) for this firmware not yet set
  up/tested from this repo — build is done, flashing isn't (same
  build-then-flash split as `STM32/CLAUDE.md`'s Build & Flash section;
  a `/flash-stm32`-equivalent skill doesn't exist for this yet).
- Apply the same checksum/echo-compare fix to `lightsensor/firmware/
  main.cpp` — not done yet, see `lightsensor/CLAUDE.md`.

Fill these in here once fixed, not in the root `CLAUDE.md`.
