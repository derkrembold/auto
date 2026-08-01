# raspi/watchdog — Context for Claude Code

Independent safety barrier for the motor. High-level rationale is in the
root `CLAUDE.md` Safety section — this file covers watchdog-specific
implementation details.

## Purpose

- Runs as its own process on the Pi, separate from `raspi/control/` and
  independent of Claude Code / the optimization loop.
- Must stop the motor on its own if, e.g., no heartbeat/command arrives
  within a timeout, or a max-speed limit is exceeded.
- Limits (max speed, heartbeat timeout, etc.) belong hardcoded in this
  code — not configurable via prompts, not enforced by Claude-side
  discipline.
- Must provide a manual emergency-stop path that works independent of
  whether the watchdog process itself, the optimization loop, or Claude
  Code is responsive.
- Poll the motor current sensor over LIN (planned separate LIN slave —
  see root `CLAUDE.md`'s LIN Protocol "Slave Topology" section) at
  roughly 4×/second and cut power if current is too high. This is a
  secondary, coarse safety net for sustained overload while the motor is
  still spinning — at ~250ms per check, it's too slow to catch a fast
  stall current spike. Fast stall protection is handled separately,
  locally on the STM32 (see `STM32/CLAUDE.md`'s Stall Detection section)
  using Hall transitions, not this LIN poll. Also useful as
  telemetry/logging data, independent of the safety use.

## Status

Not yet implemented — directory currently empty.

## Open Points (watchdog-specific)

- Concrete heartbeat timeout value.
- Concrete max-speed limit.
- Concrete current-cutoff threshold and polling rate for the LIN current
  sensor (currently just "roughly 4×/second," not yet chosen precisely).
- How the watchdog physically stops the motor — an independent LIN stop
  command would still depend on the same LIN master path used by
  `raspi/control/`; if that path fails, the watchdog needs another way to
  cut power (e.g. a separate hardware kill switch/relay) rather than
  relying on it.

Fill these in here once fixed, not in the root `CLAUDE.md` or
`raspi/CLAUDE.md`.
