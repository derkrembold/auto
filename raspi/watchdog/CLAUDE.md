# raspi/watchdog — Context for Claude Code

Independent safety barrier for the motor. High-level rationale is in the
root `CLAUDE.md` Safety section — this file covers watchdog-specific
implementation details.

## Purpose

- Runs as its own process on the Pi, separate from `raspi/control/` and
  independent of Claude Code / the optimization loop.
- Must stop the motor on its own if the connection to the client drops,
  if a client goes idle too long, or if a stall is suspected.
- Limits (max speed, timeouts, etc.) belong hardcoded in this code — not
  configurable via prompts, not enforced by Claude-side discipline.
- Must provide a manual emergency-stop path that works independent of
  whether the watchdog process itself, the optimization loop, or Claude
  Code is responsive.
- Two-layer safety check over LIN — see "Two-Layer Safety Check" below.

## Connection Model: Persistent, One Client at a Time

**`motorcontrol.py` holds one persistent connection for its whole
session** — it does not reconnect per command. This replaced an earlier
per-command-reconnect design specifically because it gives two things
for free that the earlier design couldn't:

- **Instant disconnect detection.** If the client process dies, is
  killed, or exits, the OS closes the socket — the watchdog's `recv()`
  raises `EOFError` immediately, and it stops the motor right away, no
  polling or timeout needed for this case (`Watchdog.on_disconnect()`).
- **A genuinely non-blocking client.** `motorcontrol.py` is a small
  interactive CLI (`input()` loop) — type a command, see the reply, type
  the next one, all on one open connection. No dedicated heartbeat
  process, no backgrounding, no `--noheartbeat` flag — that entire
  design (built earlier today) was replaced by this because it was
  clunky: it required a separate blocking `heartbeat` loop, and blocked
  the terminal for any other command while it ran.

**`IDLE_TIMEOUT` (20.0s, `watchdog.py`)** covers the other case: the
connection is still open, but the client has gone quiet for a while
(hung without crashing). Checked in the background `monitor()` thread.
This is deliberately much longer than instant-disconnect handling
needs — a human typing commands interactively will naturally pause
between them, and 20s gives real slack for that before treating silence
as a problem.

## Two-Layer Safety Check

- **Lower layer, the more important one: `rpm`.** The watchdog polls
  `rpm` **itself**, directly, in its background `monitor()` thread
  (`Watchdog.poll_rpm()`, every `RPM_POLL_INTERVAL` = 1.0s) — this does
  **not** depend on a client asking for `rpm`; it runs regardless of
  whether anyone's connected. This is what feeds the stall check
  (`Watchdog._check_stall()`): commanded speed nonzero, but `rpm` stays
  0 past `STALL_GRACE_PERIOD` (3.0s, covers startup torque/static
  friction) → stop. Self-polling was chosen specifically so this check
  doesn't depend on `motorcontrol.py` doing anything — it's a pure
  motor-behavior check, decoupled from whether a supervisor is even
  connected. (An earlier design had `motorcontrol.py` send `rpm`
  explicitly as a "heartbeat" to feed this — replaced because it
  conflated "is the motor stalled" with "is the supervisor alive," which
  are different questions needing different mechanisms; see Connection
  Model above for how "is the supervisor alive" is answered now.)
- **Upper layer: the current sensor** (planned separate LIN slave — see
  root `CLAUDE.md`'s LIN Protocol "Slave Topology" section). **Deferred
  deliberately** — the current-sensor hardware isn't operational yet
  (see `currentsensor/CLAUDE.md`), expected this week. Specific check,
  once it exists: **current flowing while `rpm` reads 0** is the stall
  signature (motor commanded to move, drawing current, but not actually
  turning) — cut power. More precise than a bare "current too high"
  threshold, since it directly targets the dangerous case (see
  `STM32/CLAUDE.md`'s Known Hardware Issue — current sensing on the STM32
  board itself is disabled, so this LIN-based current sensor will be the
  only current visibility that exists). Until then, `_check_stall()` is
  **interim and rpm-only** — more false-positive-prone without current
  confirmation, but better than no stall protection while the sensor
  isn't ready. Upgrading it to also check current later is a small
  addition to `_check_stall()`, not a rebuild.

At ~1×/second polling, this reacts on the order of a second, not
milliseconds — acceptable for "sustained stall," not fast enough for a
millisecond-scale current spike. That gap is exactly why the STM32-local
Hall-based approach (below) remains a real, deprioritized-not-discarded
future plan.

## Architecture: Sole LIN Master

LIN only tolerates one master on the bus. The watchdog is that master —
it's the only process that ever opens/writes `/dev/ttyS0`. It does not
decide *what* the motor should do (that's still the optimization loop's
job, via `raspi/control/`); it's the gatekeeper/actuator: it receives
command requests, validates them against its own limits, and either
puts them on the bus or refuses. It also runs its own independent
idle-timeout and stall checks and can push a stop onto the bus on its
own, unprompted.

This replaced the earlier design where `motorcontrol.py` opened the
serial port directly per-invocation — that would conflict with the
watchdog also needing bus access, and two uncoordinated processes
touching one UART can corrupt LIN frames. `raspi/control/motorcontrol.py`
is now a thin IPC client (no `RPi.GPIO`/`serial` dependency at all); the
`Lin` class and command functions (`set_speed`, `led_on`, etc.) live in
`raspi/watchdog/linbus.py`.

**IPC with `raspi/control/`:** `multiprocessing.connection`
(`Listener`/`Client`, standard library, Unix domain socket under the
hood on Linux) — chosen over raw sockets or a shared file for
simplicity/KISS: no manual framing, `send()`/`recv()` of plain strings.
One command per message (e.g. `"speed 300"`), one reply per message
(e.g. `"OK"`, `"ERR <reason>"`). The connection itself now stays open for
a whole `motorcontrol.py` session (see Connection Model above) rather
than being reopened per command.

## STM32-Local Stall Detection (Planned, Deprioritized)

**Not the current approach — see Two-Layer Safety Check above for
what's actually running.** Kept as a real future plan, not discarded,
but deliberately sequenced after `STM32/CLAUDE.md`'s standalone
(non-STM32CubeIDE) build/flash environment goal — touching that firmware
is much more practical once that tooling friction is gone. Detail lives
in `STM32/CLAUDE.md`'s own Stall Detection section, not duplicated here.

## Dry-Run Mode

`DryRunLin` in `linbus.py` — same `write()`/`read()`/`close()` interface
as the real `Lin` class, but instead of touching the serial port:
`write()` prints every byte (sync, PID+parity, each data byte, checksum)
and appends `(address, data)` to `self.writes` (so tests can assert on
it); `read()` prints and returns a test-injected fake response from
`self.read_responses[address]` if set, otherwise defaults to zero-filled
data of the correct length. Both the "print for a human" and "record
for a test" needs share this one stub, not two separate things.

`watchdog.py`'s `serve()` picks `Lin()` (real) or `DryRunLin()` based on
a `live` parameter; the `__main__` entry point sets that from an
explicit `--live` CLI flag. **Dry-run is the default** — starting
`watchdog.py` with no arguments can never move the motor, only `--live`
enables real bus access. This is a deliberate safety choice: it directly
serves the "never run without consent" rule below by making the *safe*
behavior the one that happens if someone runs this without thinking
about it.

## Test Suite (Required on Every Change)

**Policy: any change to `raspi/control/` or `raspi/watchdog/` must have
the test suite run before the change is considered done.** Applies to
Claude Code too: after editing either of these, run `pytest raspi/tests/`,
don't just deploy and call it finished.

**Framework: `pytest`.** Extra dependency vs. stdlib `unittest`, but far
less boilerplate, especially `@pytest.mark.parametrize` for the many
small (input → expected result) cases here. Needs `pip install pytest`
wherever the suite runs (not yet installed on the Pi itself).

**Location: `raspi/tests/`**, one test file per source module
(`test_watchdog.py`, `test_linbus.py`, `test_motorcontrol.py`), plus a
`conftest.py` that adds `raspi/control/` and `raspi/watchdog/` to
`sys.path` (they're separate source folders in the repo, even though
deploy flattens them into one directory on the Pi).

**Two test tiers, discovered while building step 1, not planned
upfront:**
- **Unit tests** (pure logic, no sockets/hardware) — run anywhere,
  including natively on Windows. 47 tests so far, covering: `validate()`;
  `Watchdog.execute()` against `DryRunLin`; connection lifecycle
  (`on_connect()`/`on_disconnect()` — immediate stop on disconnect,
  `check_idle()` for the 20s stale-connection case, called directly
  after manipulating `last_command_time` rather than a real 20-second
  sleep); the interim rpm-only stall check via `poll_rpm()`, including
  grace-period behavior and working correctly with no client connected
  at all; `Lin.checksum`/`Lin.addparity` (both `@staticmethod` so
  they're testable without instantiating `Lin()`, which needs real
  `RPi.GPIO`/serial); the interactive `motorcontrol.py` CLI with
  `input()` and `Client` both mocked.
- **Integration tests** (real `Listener`/`Client` over `AF_UNIX`) — need
  Linux. `multiprocessing.connection` doesn't recognize `'AF_UNIX'` as a
  family at all on native Windows Python (not just unsupported — the
  family name itself isn't recognized). Works fine on the Pi. Not yet
  written — deferred to whenever full IPC round-trip testing happens on
  the Pi (or a real Linux/WSL environment; not attempted from this
  Windows machine so far).

Remaining illustrative test case not yet covered: current-sensor-based
stall confirmation ("current flowing while `rpm`=0") — blocked on the
sensor existing at all, see Two-Layer Safety Check above.

## Status

Sole-LIN-master restructuring, dry-run mode, the test suite, and the
watchdog's safety logic are all built (`Watchdog` class in `watchdog.py`
— connection lifecycle, idle timeout, self-polled stall check). The
current-sensor upper layer is not built — sensor hardware isn't
operational yet.

**Live-hardware status (2026-08-03):** confirmed working — both the
earlier plain-relay version (`hal` read, `speed` write actually turning
the motor, `rpm` read — see `raspi/CLAUDE.md`'s LIN Protocol Timing
section) and, now, the full persistent-connection design with the
complete `Watchdog` safety logic (self-polling stall check, idle
timeout, disconnect handling) have been tested against real hardware
over `--live`. Not separately broken down which specific safety paths
(disconnect vs. idle-timeout vs. stall) were individually exercised
during that test — worth doing deliberately at some point rather than
assuming full coverage from general use.

**Bug found and fixed (2026-08-04):** `Lin.read()` (`linbus.py`) didn't
handle a bus timeout — if a slave doesn't respond within `pyserial`'s
2s timeout, `self.ser.read(1)` returns empty bytes, and the old code
crashed with `IndexError` trying to index into it. Hit live: after
flashing new firmware via `/flash-stm32` (which deliberately doesn't
reset the target, see `STM32/CLAUDE.md`), the STM32 sat halted and
didn't answer any LIN traffic, so `poll_rpm()`'s `get_rpm()` call timed
out and crashed — which killed the `monitor()` background thread
**permanently and silently** (only a printed traceback), disabling
self-polled stall detection for the rest of the process's life. Fixed
two ways: `Lin.read()` now returns an error code (`-5`) on a timed-out
read instead of crashing, and `monitor()`'s loop body is now wrapped in
try/except so a single bad poll (whatever the cause) can never kill the
thread outright — it logs and keeps polling. Both changes are pure
robustness fixes at the LIN-bus system boundary (a slave can legitimately
not respond for many reasons — halted, unpowered, bus unplugged); no
new test added since `Lin.read()`/`write()` remain outside unit-test
coverage for the same reason documented in `raspi/tests/test_linbus.py`
(need real/dry-run serial, not just pure logic).

## Open Points (watchdog-specific)

- Concrete current-cutoff threshold and exact polling rate for the LIN
  current sensor — blocked on the sensor existing; the interim rpm-only
  stall check doesn't need this yet.
- How the watchdog physically stops the motor if the watchdog *process
  itself* fails — neither disconnect-detection nor LIN-based stopping
  helps then, since nothing's driving the bus. Needs an independent
  hardware kill switch/relay as the ultimate backstop.
- Individual safety paths (disconnect detection, idle timeout, stall
  check) haven't been deliberately, separately exercised live yet — see
  Status above.
- `hal` (Hall data over LIN) might be useful for something beyond what
  it does today (e.g. further validation/diagnostics) — not prioritized,
  but don't treat it as dead/removable either.
- Whether "test suite must run on every change" stays a documented
  human/Claude discipline or becomes an actual pre-commit/CI hook later
  — not yet decided.

Fill these in here once fixed, not in the root `CLAUDE.md` or
`raspi/CLAUDE.md`.
