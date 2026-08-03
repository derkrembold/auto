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

Developing/building this doesn't need to happen on this machine — the
repo is the source-of-truth copy (same pattern as `raspi/control/` and
`currentsensor/firmware/`); the actual AVR build/flash toolchain can run
wherever that's normally set up.

## Status

Firmware source copied from the DCPS course project as a starting point
— not yet adapted/built/tested for this project, and missing LIN
addressing entirely (see Firmware section above).

## Open Points (lightsensor-specific)

- Add `addresses.hpp` (or equivalent) once this slave's PID is assigned
  — currently has no LIN address table at all.
- Verify/adapt the hardware design this firmware assumes.
- Build/flash environment for this firmware not yet set up.

Fill these in here once fixed, not in the root `CLAUDE.md`.
