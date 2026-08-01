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

## Status

Reference material only — no current-sensor hardware/firmware for this
project exists yet. Not yet designed or built.

## Open Points (currentsensor-specific)

- Design/source the actual current-sensor hardware for this project
  (informed by, but not identical to, the DCPS course project's build).
- LIN address (PID) assignment for this slave once it exists — extend
  `linaddresses.py`/`addresses.h` per the Slave Topology note in root
  `CLAUDE.md`.

Fill these in here once fixed, not in the root `CLAUDE.md`.
