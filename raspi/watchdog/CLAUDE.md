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
- **Upper layer: the current sensor.** `Watchdog.poll_current()`,
  called from `monitor()` alongside `poll_rpm()` at the same
  `RPM_POLL_INTERVAL` (the current sensor's own on-board averaging
  window is ~1s anyway, see `currentsensor/CLAUDE.md`'s `countmax`/
  `OCR1A` tuning, so polling it faster wouldn't get fresher data).
  **Two checks off the same current read:**
  - **Overcurrent hard stop (added 2026-09-10, this one DOES act).**
    `abs(val1) > OVERCURRENT_STOP_THRESHOLD` (15A) — or `val2`, checked
    the same way for when a second motor is wired there — calls
    `_stop_motor()` unconditionally, whether the rotor is turning or
    not. 15A is inside the ACS712xLCTR-20A's linear range (saturates
    ~20A, raw ADC tops ~25A) and above the motor's ~16-17A rated draw.
    Backstop for *sustained* overcurrent (stalled-and-grinding);
    reaction ~1-3s (sensor averaging + poll interval), NOT a fast
    transient crowbar — a real catastrophic spike (a stalled winding
    can pull hundreds of amps) just pegs the sensor. **`_stop_motor()`
    currently stops the one addressable motor; once a second motor is
    wired to `val2`, an overcurrent on either channel must stop BOTH
    (see the §6.3 point in the planned Watchdog extensions below).**
  - **Stall signature — still observe-only.** `abs(val1) >
    CURRENT_STALL_THRESHOLD` (0.15A) **while the last known `rpm` reads
    0** (motor commanded to move, drawing current, not turning). More
    precise than a bare high-current threshold since it targets the
    dangerous case directly. **Logs a conspicuous message but does
    **not** call `_stop_motor()`** — the sensor only started working
    reliably after several rounds of real-hardware bugfixing
    (2026-08-06 → 08-11, see `currentsensor/CLAUDE.md`'s Status), not
    yet trusted to autonomously cut power on *this* subtler signal;
    promote it once it's proven itself over a real observation period.
    Only `val1` here — `val2` is reserved for a second motor, not a
    redundant reading (see `currentsensor/CLAUDE.md`'s Hardware
    section). `_check_stall()` (the lower, rpm-only layer) plus this
    new overcurrent stop are the layers that actually stop the motor
    today.
  Both thresholds (`OVERCURRENT_STOP_THRESHOLD`, `CURRENT_STALL_
  THRESHOLD`) are named constants in `watchdog.py` so they're easy to
  retune; `CURRENT_STALL_THRESHOLD` needs headroom above ACS712
  chip-to-chip offset tolerance (~0.05-0.09A observed on real
  hardware).

At ~1×/second polling, this reacts on the order of a second, not
milliseconds — acceptable for "sustained stall," not fast enough for a
millisecond-scale current spike. That gap is exactly why the STM32-local
Hall-based approach (below) remains a real, deprioritized-not-discarded
future plan.

**Lower layer confirmed acting autonomously on real hardware
(2026-08-22, battery power, no transformer).** Manual `speed 200` via
`motorcontrol.py` (11:50:10.393) didn't get the motor moving; the
watchdog's own `_check_stall()` fired at 11:50:13.602 — exactly
`STALL_GRACE_PERIOD` (3.0s) later — and stopped the motor on its own,
~10s *before* the user's own manual `speed 0` (11:50:23.323) reached
it. Confirms the self-polling design goal directly: the check reacted
correctly and faster than the human at the controls, with no client
action needed to trigger it. Whether the slow start itself was
battery-specific or just this speed being close to the motor's
breakaway/static-friction threshold is unresolved — only one data
point, not investigated further per the user's own read ("das finde
ich jetzt völlig uninteressant").

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
`Lin` class and command functions (`set_speed`, `set_pi`, etc.) live in
`raspi/watchdog/linbus.py`.

**IPC with `raspi/control/`:** `multiprocessing.connection`
(`Listener`/`Client`, standard library, Unix domain socket under the
hood on Linux) — chosen over raw sockets or a shared file for
simplicity/KISS: no manual framing, `send()`/`recv()` of plain strings.
One command per message (e.g. `"speed 300"`), one reply per message
(e.g. `"OK"`, `"ERR <reason>"`). The connection itself now stays open for
a whole `motorcontrol.py` session (see Connection Model above) rather
than being reopened per command.

## Planned Multi-Process Architecture (Two-Motor Vehicle)

**Everything in this section is planned, not built — captured
2026-09-07 from the user's own design draft (originally a standalone
`BLDC_System_Specification.md`, folded into this file and deleted the
same day — see git history for the original wording). Subject to
change; the actual redesign happens interactively between the user and
Claude Code as it's built, not by following this plan mechanically.
Explicitly **not** a from-scratch redesign** — the user wants to keep
as much of the existing, proven architecture (persistent IPC
connection, dry-run default, self-polled rpm stall check, etc.) as
possible and build additively on top of it, specifically *because* it's
already known to work. See root `CLAUDE.md`'s Two-Motor Vehicle
Architecture section for the vehicle-level context this sits under.

**Four planned processes** (today: one `watchdog.py` process + one
interactive `motorcontrol.py` client):
```
Prozess 1: Joystick
→ reads a Logitech controller over Bluetooth
→ computes speed left/right (differential drive: vorwaerts ± lenkung)
→ sends over IPC to the Watchdog (replaces motorcontrol.py's role for
  driving, which stays available for manual/diagnostic commands)
→ logs

Prozess 2: Watchdog (extends today's watchdog.py, not a rewrite)
→ receives speed from the Joystick process over IPC
→ relays speed to both STM32 controllers, low lag between the two
  (steering correctness depends on this — a lag between left/right
  speed commands would show up as unintended veering)
→ monitors rpm and lag (speed vs. rpm) per motor
→ monitors current over LIN (once the external current-sensor module
  exists, see root CLAUDE.md's Two-Motor Vehicle Architecture)
→ monitors the IFM sensors (MQTT or direct IP — TBD)
→ runs the Stall/Stiction Response (see below) — or possibly Process 1,
  not yet decided
→ logs

Prozess 3: Learning Algorithm (Decision Tree)
→ runs in the background, reads the logging database
→ improves the Stall/Stiction Response over time (see below)

Prozess 4: Webserver
→ shows status/rpm/current/IFM sensor data
→ reachable over the Pi's own WiFi access point, phone browser
```

**Joystick control mapping (planned):**
```
vorwaerts = joystick Y axis  (-1.0..+1.0)
lenkung   = joystick X axis  (-1.0..+1.0)

motor_links  = clamp(vorwaerts + lenkung, -1.0, +1.0)
motor_rechts = clamp(vorwaerts - lenkung, -1.0, +1.0)
speed_links  = motor_links  × MAX_RPM
speed_rechts = motor_rechts × MAX_RPM
```

**Watchdog extensions (planned) — important emphasis from the user
(2026-09-07): when the STM32's own kickstart mechanism (see
`STM32/CLAUDE.md`'s Planned Redesign section) fails to break a stall,
the Pi-side watchdog should stop the motor and wait for the user to
physically intervene ("anschieben"), not keep retrying on its own —
if the firmware's own kickstart couldn't do it, further automated
retries from the Pi side aren't expected to help either.** Once a
second motor exists, this should stop **both** motors, not just the
stuck one — an uncontrolled single-motor-only state on a differential-
drive vehicle isn't a safe/predictable state to keep running in. The
user's own words: "das kann in den Watchdog rein... gerne können wir
aber auch zu einem späteren Zeitpunkt darüber diskutieren, wenn es
soweit ist" — a real design intent, not yet detailed, revisit when the
second motor is actually being built.

Other planned watchdog extensions, same design draft:
```
Lag monitoring per motor:
  (speed - rpm) too large for too long → motor is fighting → trigger
  Stall/Stiction Response

Overcurrent monitoring (once the external current-sensor module
exists):
  current > WARNUNG_CURRENT (e.g. 25A) → log a warning
  current > MAX_CURRENT (e.g. 30A) → immediate speed=0, ERROR_OVERCURRENT

IFM sensor monitoring:
  O3D (front): obstacle closer than MIN_ABSTAND → immediate speed=0
  LiDAR (side): obstacle closer than MIN_ABSTAND → steering correction
  Ultrasonic (side/rear): obstacle closer than MIN_ABSTAND → warning +
    steering correction; also the O3D's fallback in direct sunlight

Normal operation: speed != 0 and rpm approaches speed → ok; speed == 0
and rpm == 0 → ok. Problem, per motor: speed != 0 and rpm stays 0 →
Stall/Stiction Response.

Note: rpm_left != rpm_right is normal during steering — each motor is
only ever compared against its own commanded speed, never against the
other motor's.
```

## Planned Stall/Stiction Response (Building Blocks + Learning)

**Same status as the section above — planned, not built, 2026-09-07,
subject to change. Grouped with the Planned Multi-Process Architecture
above per the user's own framing ("§7 ist mit §6 verwandt, die
gehören zusammen behandelt") — this is what Process 2 (or 1, TBD) runs
when it detects a stall.**

**A first real, working precursor of this idea exists as of 2026-09-09
— in `raspi/control/capture_step_response.py`, not here yet.** Built
after `watchdog.py`'s new `burst` verb was confirmed on real hardware
to reliably escape a specific, reproducible Mittelrast stall (see
`STM32/CLAUDE.md`). Same spirit as the building-block idea below
(small composable moves, combined into sequences, logged with outcome)
but scoped to today's single-motor bench, not the planned multi-process
vehicle architecture: a fixed catalog of 7 strategies (`speed0`/
`speed_plus`/`speed_minus`/`pulse_plus`/`pulse_minus`/`burst_cw`/
`burst_ccw`), 2-3 random picks per sequence with hand-picked
constraints (max 1 `burst`/2 `pulse`, no immediate repeat, ≥100ms
between steps), one recovery attempt + one retry-as-verification, and
every outcome appended to `recovery_sequences.csv` (never rotated,
meant to keep growing as real training data). See
`raspi/CLAUDE.md`'s `capture_step_response.py` entry and the script's
own module docstring for the full design. **Confirmed live the same
day to generalize beyond the one specifically-known stuck position**
(recovered a different, previously-uncharacterized Mittelrast) —
real evidence this general approach works, not just the one hand-tuned
recipe. Whether/how this precursor folds into the planned Process 2/
Learning Algorithm below, once the multi-process architecture actually
gets built, is not yet decided.

**Design idea: small composable "building block" commands, combined
into sequences, rather than one fixed hardcoded recovery routine:**
```
pulse:      the STM32's own kickstart pulse sequence (see
            STM32/CLAUDE.md's Planned Redesign section)
neg_pulse:  the same sequence, reversed direction
neg_speed:  briefly command a negative speed
pos_speed:  briefly command a positive speed, higher than the setpoint
speed_null: briefly command speed=0, let the motor relax
```
Every sequence ends the same way: send the original setpoint, then
read `rpm`. Optionally, `hal` and/or `current` can be read before and
after any block (always in pairs) for extra context — `hal` costs LIN
round-trip time, so use deliberately, not on every block; `current`
tells whether the motor is fighting a load (high) or spinning free
(low). Blocks combine freely, e.g. `neg_speed → pulse`,
`neg_speed → pos_speed` (repeated, this is a "vibrate" pattern — see
Learning Algorithm below), `speed_null → pos_speed`.

**Sequence** (per motor, once `rpm == 0` is detected):
```
1. Wait: the STM32 already attempts its own 6x kickstart (up to 1s,
   see STM32/CLAUDE.md's Planned Kickstart Algorithm)
2. Read status: kickstartCounter, errorCode
3. Combine building blocks (per the Learning Algorithm below)
   → optionally read hal before the sequence
   → run the sequence
   → at the end: send the original setpoint, read rpm
   → optionally read hal after the sequence
4. rpm != 0? → closed loop, done
5. rpm == 0? → try a new sequence
6. No strategy succeeds → hard stop (see the Watchdog extensions above)
```

## Planned Learning Algorithm (Decision Tree)

**Same planned/not-built/subject-to-change status. Mid-term priority
— sequenced after the Multi-Process Architecture and Stall/Stiction
Response above are actually built.** The Stall/Stiction Response
section's 2026-09-09 precursor is already producing real
`recovery_sequences.csv` rows (sequence + outcome, one per recovery
attempt) — genuine, if early, training data for whatever this decision
tree eventually looks like, not just a hypothetical future format.

A decision tree over the 5 building blocks above, max depth 4 (5→25→
125→625 possibilities per depth level — bounded, doesn't explode).
`hal` is not itself a building block but a togglable context source,
three modes (always read in vor/nach pairs): no `hal`, `hal` once
before+after the whole sequence, or `hal` between every block. Each
tree node (path) tracks its success rate, overall and per `hal` mode;
the algorithm picks the highest-success-rate path, adapting to the
current `hal` state where available. Runs as its own background
process, online learning, doesn't block normal operation — see
Process 3 above. **The point of the building-block approach**: a
sequence like `neg_speed → pos_speed → neg_speed → pos_speed` (a
"vibrate" pattern) doesn't need to be hardcoded — the learner can
discover it on its own once repeated data shows it works, from
`pos_speed`/`neg_speed` alone.

## Planned Logging Database

**Same planned/not-built/subject-to-change status. Important for
debugging** (the user's own framing, 2026-09-07) — both the Joystick
and Watchdog processes write into a shared SQLite database; the
Learning Algorithm reads from it. Planned fields: timestamps, joystick
input, computed/sent speed per motor, `rpm`/lag/current per motor, IFM
sensor readings, Hall states, status (error code, kickstart counter),
and — per Stall/Stiction Response invocation — which block sequence
ran, whether it succeeded, and how long it took. This is the training
data the Learning Algorithm above depends on.

## Planned Web UI

**Same planned/not-built/subject-to-change status. Sequenced after the
Learning Algorithm above** (the user's own ranking, 2026-09-07) — a
page served from the Pi's own WiFi access point (`http://192.168.4.1`),
phone-browser accessible: `rpm`/setpoint/current per motor, IFM sensor
readings, error/status, kickstart counter, GPS position (once that
exists, see root `CLAUDE.md`'s Long-Term Roadmap). Optional: a
touchscreen joystick and an emergency-stop button in the page itself.

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

**`--debug`** (added 2026-08-11, redesigned around `raspi/control/
logsetup.py` on 2026-08-12): controls only whether the full LIN bus-call
trace also echoes to the **terminal** live. The **log file always has
full detail regardless of this flag** — that's the point: the original
"motor sometimes doesn't start" investigation was nearly lost because
`--debug` wasn't on before the rare hang happened. Once the file always
captures everything, "forgot to enable verbose logging before the bug
happened" stops being possible.
```
python3 watchdog.py --live --debug   # verbose trace also shows live
python3 watchdog.py --live           # quiet terminal, file still full detail
```

**`raspi/control/logsetup.py`** — shared by all four scripts
(`watchdog.py`, `motorcontrol.py`, `validate_speed.py`,
`capture_step_response.py`; importable from either `control/` or
`watchdog/` since deploy flattens them into one directory, see
`raspi/CLAUDE.md`'s Deployment Pattern). `logsetup.configure(name,
path, terminal_level)`:
- **Rotates, doesn't overwrite or unboundedly append**: at startup, an
  existing log gets renamed to `<name>.log.1` (overwriting whatever was
  there from two starts ago), then a fresh file begins. Chosen over
  pure overwrite (loses a rare bug's evidence if a restart happens
  before the log's been copied off — a real risk during this exact
  bus-hang investigation) and over pure append (unbounded growth, no
  real need for more than one generation of history in practice).
- **File handler**: always attached, always `DEBUG` level — every
  `logger.debug()`/`.info()`/`.warning()` call lands in the file, no
  exceptions.
- **Terminal handler**: optional (`terminal_level=None` skips it
  entirely), independently leveled. `watchdog.py` passes `DEBUG` if
  `--debug` else `INFO` (quiet by default, verbose bus-tracing only on
  request). `motorcontrol.py` passes `INFO` (always show — no
  high-frequency polling noise there, every line is an explicit typed
  command). `validate_speed.py`/`capture_step_response.py` pass `None`
  — their stdout is reserved for CSV output (e.g. when redirected into
  a file), so their protocol-level send/receive trace goes to
  `validate_speed.log`/`capture_step_response.log` only, never mixed
  into the CSV stream.

**Where the LIN-level tracing lives:** in `linbus.py`, via
`logging.getLogger("watchdog.linbus")` — a *child* of the `"watchdog"`
logger `serve()` configures, so it automatically propagates to the same
handlers (file always, terminal per `--debug`) with zero extra wiring.
`Lin` itself has no `debug` parameter anymore — it just calls
`logger.debug()`/`.warning()` unconditionally at the exact call site
where `address`/`data`/`ret` are naturally available (`write()`,
`read()`), and the logging framework's own level-based filtering
decides what actually gets emitted where. This is also why `Watchdog`
no longer has its own `debug` flag or per-tick prints — `poll_rpm()`/
`poll_current()` just call `linbus.get_rpm()`/`get_current()` as before.

**Format** — one-time session header (in the file, via `logger.info()`)
plus a `%(asctime)s.%(msecs)03d  %(levelname)-7s %(message)s` line format
(`logsetup.LOG_FORMAT`/`LOG_DATEFMT`) applied uniformly by the
`Formatter`, so timestamps aren't hand-built at each call site. The
`levelname` field was added 2026-08-12 (see `analyze_logs.py` below) —
without it, `WARNING`/`ERROR` lines were textually indistinguishable
from `INFO`/`DEBUG` ones, so a tool couldn't reliably filter by
severity, only by guessing at message wording:
```
09:15:03.001  INFO    === watchdog.py — LIVE bus [debug] ===
10:23:44.998  DEBUG   [client]  -> write cntl3mot   data=['0x01', '0xf4']
10:23:45.001  DEBUG   [client]  -> read  st2mot
10:23:45.014  DEBUG   [client]  <- read  st2mot     ret=0  data=['0x20', '0x03']
10:23:46.002  DEBUG   [poll]    -> read  st0cur
10:23:48.002  WARNING [poll]    no response from slave (st0cur)
10:23:48.004  DEBUG   [poll]    <- read  st0cur     ret=-5  data=[]
```
- `[client]`/`[poll]` shows which thread triggered the call
  (`threading.current_thread()`-based, not threaded through as a
  parameter) — `Watchdog.execute()` always runs on the main thread,
  `Watchdog.monitor()` in its own background thread, so this is
  reliable without extra bookkeeping.
- `Lin.write()` logs a single `->` line by design, no matching `<-` — a
  LIN write gets no slave reply, so there's nothing to wait for; the
  write's own local echo-check outcome isn't logged (a possible later
  refinement, not done now).
- `Lin.read()` logs a `->`/`<-` pair. An unmatched `->` with no
  following `<-` pinpoints the *exact* call that hung, instead of
  "somewhere between these two log lines" (as precise as the
  2026-08-11 investigation could get). The `->` is logged from inside
  the locked section (i.e. once `self.lock` is actually held), so pairs
  from different threads can never interleave — no correlation ID
  needed (a client-request-ID scheme was discussed and deliberately
  not built — see Open Points below).
- `ret` is the bare numeric code only, no inline text description —
  code-to-meaning is fixed reference info (see `linbus.py`'s existing
  comments for what each negative value means), not per-line text; also
  keeps the format friendly to a future log-analysis tool (see below),
  which would want to filter/count on a stable numeric value, not
  free-text that could drift in wording.
- `data=[...]` on a failed read is whatever bytes actually arrived
  before the failure (not always empty) — e.g. `data=['0x20']` with
  `ret=-5` means one byte got through before it stalled, vs `data=[]`
  meaning nothing arrived at all. More diagnostic than the original
  always-`[]`-on-error behavior.
- No decoded `value=` field at this layer (e.g. `800` for rpm, an amps
  figure for current) — `Lin.read()` only knows raw bytes, decoding
  happens one layer up in `get_rpm()`/`get_current()`/etc., which don't
  have their own logging hook (yet). Noted as a possible follow-up, not
  done in this pass — reading `data=[...]` and decoding by hand is the
  current tradeoff.
- Symbolic pid names (`cntl3mot`, `st0cur`, ...) come from
  `linaddresses.py`'s generated `constants.pid_names` dict (pid value ->
  its own name) — added to `generate_addresses.py`'s `render_python()`
  specifically for this; falls back to hex if a pid is somehow unknown.
- `DryRunLin` (used when not `--live`) deliberately does **not** get
  this treatment — it already has its own verbose per-call print
  (`[dry-run] write sync = ...` etc.), and dry-run has no real timing/
  hang failure mode to diagnose in the first place.

`motorcontrol.py`/`validate_speed.py`/`capture_step_response.py` log
their own `-> <command>` / `<- <reply>` pairs at the IPC layer (what was
sent to/received from the watchdog), independent of and at a higher
level than the LIN bus-call trace above — see their own module
docstrings.

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
current-sensor upper layer is also built (`poll_current()`,
2026-08-11): the overcurrent hard stop (15A, added 2026-09-10) acts,
the subtler stall-signature check is still observe-only — see
"Two-Layer Safety Check" above.

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
- **Client-side correlation ID** (discussed 2026-08-12, deliberately not
  built): `motorcontrol.py`/etc. could generate an ID per command, send
  it over the wire, and have the watchdog thread it through to its own
  log lines, so "everything about this one command" is `grep`-able
  across both logs directly. Not built because today's protocol is
  strictly synchronous (one client, one command in flight at a time) —
  timestamp + sequential order already disambiguate without it. Would
  become worth it if the protocol ever stops being strictly one-at-a-
  time, or if timestamp-based cross-log correlation turns out to be
  annoying in practice (revisit then, not preemptively).
- **Log-analysis tool** (built 2026-08-12): `raspi/analyze_logs.py` +
  the `/analyze-logs` skill — parses the logs this section documents
  and flags: unmatched `->` calls (hangs), non-zero `ret` codes, calls
  exceeding a fixed latency threshold, `data=[...]` lengths that don't
  match `addresses.json`'s `bytes` field for that message, `WARNING`/
  `ERROR` lines (now reliably filterable — see the `levelname` note
  above), and poll-loop cadence gaps. Read-only, no motor
  interaction — see `raspi/analyze_logs.py`'s own docstring for exact
  check definitions rather than duplicating them here.

- **Blocked on STM32/CLAUDE.md's Planned Redesign section (see there
  for detail):** once the firmware gets a `reset` command and a
  restructured 4-byte `status` reply, `watchdog.py` needs a matching
  `reset` verb and `linbus.py`/`get_motor_counters()`-equivalent needs
  updating for the new field layout (including the new `errorCode`).
  Not started.

Fill these in here once fixed, not in the root `CLAUDE.md` or
`raspi/CLAUDE.md`.
