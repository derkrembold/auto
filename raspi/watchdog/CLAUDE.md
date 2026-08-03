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

## Architecture: Sole LIN Master

LIN only tolerates one master on the bus. The watchdog is that master —
it's the only process that ever opens/writes `/dev/ttyS0`. It does not
decide *what* the motor should do (that's still the optimization loop's
job, via `raspi/control/`); it's the gatekeeper/actuator: it receives
command requests, validates them against its own limits (max speed,
heartbeat freshness), and either puts them on the bus or refuses. It
also runs its own independent heartbeat-timeout and current-polling
checks and can push a stop onto the bus on its own, unprompted.

This replaces the current design where `motorcontrol.py` opens the
serial port directly per-invocation — that would conflict with the
watchdog also needing bus access (e.g. for current-sensor polling), and
two uncoordinated processes touching one UART can corrupt LIN frames.
`raspi/control/` needs to change to send requests to the watchdog
instead of writing to the bus itself.

**IPC with `raspi/control/`:** `multiprocessing.connection`
(`Listener`/`Client`, standard library, Unix domain socket under the
hood on Linux) — chosen over raw sockets or a shared file for
simplicity/KISS: no manual framing, `send()`/`recv()` of plain strings.
Protocol is deliberately minimal: one command per message (e.g.
`"speed 300"`, `"stop"`), one reply per message (e.g. `"OK"`,
`"ERR <reason>"`).

## Build Order

1. **Sole-LIN-master restructuring first** (Architecture section above)
   — the watchdog process + IPC server/client skeleton needs to exist
   before there's a real interface to stub out.
2. **Dry-run mode** (below) — needed soon, right after #1. Swap the
   real LIN I/O for the stub inside the now-existing skeleton.
3. **Test suite** — exercises the skeleton via dry-run mode.
4. **Watchdog's actual safety logic** (heartbeat timeout, max-speed
   limit, current polling) — built/tested last, using #1-3.

## Dry-Run Mode

A stub swap-in for the real LIN bus I/O: same method interface as the
real `Lin` class (`write()`, `read()`, etc.), but instead of touching
the serial port, it prints what it would have sent to the terminal.
Selected via a flag/env var at watchdog startup — the rest of the
watchdog's logic (command validation, heartbeat, current thresholds)
runs unchanged and doesn't know which one it's talking to.

This is how the watchdog/`motorcontrol.py` IPC relay gets developed and
tested — you can watch the exact command sequence that would go out on
the wire, with zero risk of the motor actually moving, consistent with
the "never run without consent" rule below. Prioritize this over the
other watchdog features (heartbeat timeout, max-speed limit, current
polling) — those all need this dry-run path to be testable safely first.

The stub must also *record* what it would have sent (e.g. a list of
decoded commands), not just print it — printing is for a human watching
the terminal, but the test suite below needs something to assert
against programmatically. Both purposes share the same stub.

## Test Suite (Required on Every Change)

**Policy: any change to `raspi/control/` or `raspi/watchdog/` must have
the test suite run against dry-run mode before the change is considered
done.** No real hardware needed — this is the point of dry-run mode.
Applies to Claude Code too: after editing either of these, run the
suite, don't just deploy and call it finished.

Illustrative starting set of test cases (not exhaustive, refine once
built):
- `speed <value>` produces the correct decoded LIN write (sync, PID,
  data bytes, checksum) for a few representative values.
- Out-of-range `speed` values get clamped as expected.
- `on`/`off`/`hal`/`rpm`/`temp` each produce/parse the correct bytes.
- Watchdog refuses a request above the configured max-speed limit.
- Watchdog issues a stop after the heartbeat timeout with no new
  command.
- Watchdog issues a stop when a simulated current reading exceeds the
  configured threshold.

Not yet designed: test framework choice (`pytest` vs. stdlib
`unittest` — leaning `pytest` for less boilerplate, but that's an extra
dependency vs. KISS/zero-dependency `unittest`; not decided), where the
suite lives (e.g. `raspi/tests/`), and whether "must run on every
change" is just a documented human/Claude discipline for now or should
become an actual pre-commit/CI hook later.

## Status

Not yet implemented — directory currently empty.

## Open Points (watchdog-specific)

- Concrete heartbeat timeout value.
- Concrete max-speed limit.
- Concrete current-cutoff threshold and polling rate for the LIN current
  sensor (currently just "roughly 4×/second," not yet chosen precisely).
- How the watchdog physically stops the motor if the watchdog *process
  itself* fails — LIN-based stopping doesn't help then, since nothing's
  driving the bus. Needs an independent hardware kill switch/relay as
  the ultimate backstop, separate from the LIN-based stop path above.
- Exact dry-run activation mechanism (flag vs. env var) — minor, not
  blocking.

Fill these in here once fixed, not in the root `CLAUDE.md` or
`raspi/CLAUDE.md`.
