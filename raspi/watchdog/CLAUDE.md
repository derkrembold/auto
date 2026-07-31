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

## Status

Not yet implemented — directory currently empty.

## Open Points (watchdog-specific)

- Concrete heartbeat timeout value.
- Concrete max-speed limit.
- How the watchdog physically stops the motor — an independent LIN stop
  command would still depend on the same LIN master path used by
  `raspi/control/`; if that path fails, the watchdog needs another way to
  cut power (e.g. a separate hardware kill switch/relay) rather than
  relying on it.

Fill these in here once fixed, not in the root `CLAUDE.md` or
`raspi/CLAUDE.md`.
