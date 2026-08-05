# lightsensor — Context for Claude Code

This folder holds firmware for the planned light-sensor LIN slave — see
root `CLAUDE.md`'s LIN Protocol "Slave Topology" section ("2 motor
slaves, 1 current sensor, 1 light sensor" planned expansion).

## Firmware

`firmware/` holds the DCPS course project's light-sensor ATmega328P
source (`main.cpp`, `errors.hpp`, `Makefile`) — starting point for this
project's own light-sensor slave, not yet adapted to this project. Only
source files were copied — build artifacts and editor backups were
intentionally left out, same as `currentsensor/firmware/`.

**No `addresses.hpp` here** — unlike the current-sensor firmware (see
`currentsensor/CLAUDE.md`), this `main.cpp` only includes `errors.hpp`,
no LIN address table. Either the DCPS course project never finished
wiring this sensor onto the LIN bus, or it wasn't in scope for it —
either way, an address table needs to be added here once this slave's
PID is assigned (see Slave Topology note in root `CLAUDE.md`).

**Build: working (2026-08-05).** Same setup as `currentsensor/CLAUDE.md`'s
Firmware section — `light.elf`/`light.hex` build from this folder's own
`Makefile` (standalone copy, not a live reference into
`C:\Users\rembo\Documents\ATMEGA328\Controller\`), no `CORE_OBJECTS`
needed since `main.cpp` doesn't use the Arduino Wiring layer. See that
section for the full reasoning, it applies here unchanged.

**Not yet done here (unlike `currentsensor`):** the checksum/echo-compare
fix — `main.cpp` currently has no `checksum()` function and doesn't
validate echoed bytes on its LIN replies at all (matches the "maybe
never finished wiring this sensor onto the bus" theory above). Worth
doing before this slave is trusted on a real bus, once its own LIN
addressing exists to test against.

Developing/building doesn't *need* to happen on this machine — the repo
is the source-of-truth copy (same pattern as `raspi/control/` and
`currentsensor/firmware/`) — but as of the above, it also works fine
here if that's convenient.

## Status

Firmware builds cleanly (`light.hex` produced, 2026-08-05) but is
functionally further behind `currentsensor`'s: no LIN addressing at all,
no checksum validation on its LIN replies, not yet adapted to this
project, not yet flashed to real hardware.

## Open Points (lightsensor-specific)

- Add `addresses.hpp` (or equivalent) once this slave's PID is assigned
  — currently has no LIN address table at all.
- Add the checksum/echo-compare fix `currentsensor/firmware/main.cpp`
  already has (see Firmware section above) — not done here yet.
- Verify/adapt the hardware design this firmware assumes.
- Flash environment (`avrdude`/programmer) not yet set up/tested from
  this repo — build is done, flashing isn't.

Fill these in here once fixed, not in the root `CLAUDE.md`.
