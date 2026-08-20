# Auto — Automated BLDC Motor Test and Optimization Tool

This file is organized so a future split into separate `concept.md` /
`architecture.md` files (if it ever gets overloaded) is just "cut this
section out" — no rewriting needed.

# Concept

The "why" — rarely changes.

## Goal

Autonomous optimization loop for a BLDC motor control algorithm on an
STM32 controller. A parameter set is built, flashed, the motor runs for a
test interval, the speed is measured, control metrics are computed from
that, and the next parameter set is derived from them.

## Documentation Language

Documentation in this repo is in English. Some descriptions (e.g. parts
of `STM32/CLAUDE.md` and `STM32/notes.md`, copied from pre-existing
German working notes) are still in German — translate them to English
as you touch them, rather than leaving them as a standing exception.

# Architecture

The "how" — evolves as the system gets built out.

## Machines/Devices Involved

- **STM32 host (Windows, this machine)**: Claude Code runs here.
  STM32CubeIDE/STM32_Programmer_CLI is installed here, and the Saleae
  Logic Pro 16 is also connected here.
- **STM32 controller**: Runs the control algorithm, drives the BLDC motor.
- **Raspberry Pi**: A pure execution node with no AI of its own. Sends
  LIN bus commands (Speed, 0 = stop) to the motor controller. Is
  remote-controlled by Claude Code over SSH (upload scripts, run them,
  read back results).
- **Saleae Logic Pro 16**: Records the motor's 3 Hall sensor channels
  plus a trigger channel. Precision speed measurement for PI-parameter
  optimization, and for validating the LIN `rpm` reading against ground
  truth — see the Measurement bullet below. Not part of the operational/
  production system — `raspi/watchdog/` reads `rpm` over LIN for that,
  see its CLAUDE.md.

## Data Flow / Control Channels

- **Control (LIN, already implemented):** Raspi → STM32 controller.
  Command: set speed (0 = stop). All communication with the STM32 is
  over LIN, always — the Saleae is a measurement tool, not a control or
  operational data channel.
- **Measurement (Saleae, non-invasive, for optimization + validation
  only):** The 3 Hall sensor signals are needed for commutation anyway —
  the Saleae just taps them, without requiring any firmware changes.
  Instantaneous speed is computed from them in software (time between
  edge transitions). Two purposes: (1) precise speed feedback for tuning
  the PI parameters, (2) validating the LIN `rpm` reading against this
  ground truth — see the open "does `speed` really mean RPM?" question
  below. This is a dev-time/lab tool, not part of the deployed/
  operational system — the watchdog's own `rpm` polling over LIN (see
  `raspi/watchdog/CLAUDE.md`) is the operational speed-monitoring
  channel, and is unaffected by this Saleae scoping.
- **Trigger pin:** An additional free GPIO pin on the STM32 controller is
  set high when the control algorithm starts (directly in the code path
  that also triggers motor start) and set low again on stop. This pin
  runs as the 4th channel in the Saleae capture and serves as a hardware
  trigger for capture start — no software synchronization between
  systems needed.

## Repo Structure

```
Auto/
├── addresses.json          Single source of truth for LIN PIDs (see LIN Protocol section)
├── generate_addresses.py   Generates addresses.md + writes directly to every consuming file
├── addresses.md            Generated "at a glance" occupied/free PID map
├── run_experiment.py       Standalone P/I grid/gradient-search point runner (see raspi/CLAUDE.md)
├── STM32/          Firmware + build/flash automation (STM32 CLI)
├── raspi/
│   ├── control/    LIN master code (speed command) — already implemented
│   └── watchdog/   Independent safety barrier, runs separately from the rest
├── currentsensor/  Planned LIN slave — firmware/ + reference notes
├── lightsensor/    Planned LIN slave — firmware/
├── saleae/
│   ├── capture_config/   Channel mapping, trigger setup, sample rate
│   └── exports/          Raw capture exports per test run
├── saleae_mcp/     MCP server wrapping the Saleae Automation API (see saleae/CLAUDE.md)
├── analysis/       Speed calculation from Hall edges, control metrics
└── runs/           Per iteration: parameter set, raw data, metrics
```

`raspi/*` is developed/versioned here in the repo, but deployed to the
Raspi via SSH/SCP — the Raspi itself is only a deployment target, not a
git checkout.

Pi-specific details (SSH access, deploy mechanics, LIN protocol quirks,
motor-execution consent rule) live in `raspi/CLAUDE.md`, not here — this
file stays scoped to whole-system concept/architecture.

Saleae-specific details (channel mapping, trigger/sample-rate config) live
in `saleae/CLAUDE.md`, not here.

Analysis-specific details (speed calculation, cost function/metrics) live
in `analysis/CLAUDE.md`, not here.

STM32-specific details (firmware, build/flash, motor specs, LIN slave
side) live in `STM32/CLAUDE.md`, not here.

Current-sensor-specific details (planned LIN slave, reference material
from a related university course project) live in
`currentsensor/CLAUDE.md`, not here.

Light-sensor-specific details (planned LIN slave, firmware starting
point from the same course project) live in `lightsensor/CLAUDE.md`,
not here.

## Experiment Runner (`run_experiment.py`)

**Built 2026-08-19.** Standalone, no-Claude-needed script (repo root)
that runs one full grid/gradient-search point end to end: physical
pre-flight checklist → P/I delta input (as CLI args or interactive
prompts) → motor-start consent → sets `KP`/`KI` via `raspi/control/
capture_step_response.py --p-delta/--i-delta` (which itself sends the
`pi` command first and aborts before touching the motor if the
watchdog rejects the range) → arms the Saleae in `trigger` mode, runs
the motor, retries up to 3x if the trigger false-fires on EMI noise →
`raspi/analyze_logs.py` sanity check → Hall-vs-LIN-plus-current overlay
plot. This is the intended single-point mechanism a future grid/
gradient search loop (see the Goal above) would call repeatedly with
different `--p-delta`/`--i-delta` values, not just a one-off
convenience script.

Deliberately does **not** re-check the P/I range itself — the
watchdog's own `validate()` (`raspi/watchdog/watchdog.py`'s
`PI_DELTA_MIN`/`MAX`) is the single source of truth for that, avoiding
two independent range definitions drifting apart over time. See
`raspi/CLAUDE.md`'s `capture_step_response.py`/`pi` entries,
`saleae/CLAUDE.md`'s Trigger pin section (the false-trigger retry logic
this reuses), and `analysis/CLAUDE.md` (`hall_rpm.py`,
`has_sustained_high()`) for the pieces this wires together — this
section only covers the orchestration, not each piece's own design
history.

**Confirmed end-to-end on real hardware the same day, including a real
bug found and fixed live.** First run: the `watchdog.log`/
`capture_step_response.log` fetch step didn't check `scp`'s return
code, so one transient fetch failure was silently swallowed and
`analyze_logs.py` crashed downstream with a confusing
`FileNotFoundError` instead of a clear message — the actual experiment
(checklist through the plot) had completed successfully regardless.
Fixed: each log fetch retries up to 3x (matching the `/analyze-logs`
skill's own documented `motorpi.local` mDNS-flakiness note), only
successfully-fetched files are passed to `analyze_logs.py`, and a
still-failing fetch after retries prints a clear warning instead of
crashing anything downstream. Second run (`pi 0.01 0.01`, a real
nonzero delta) confirmed fully clean: real trigger caught on the first
attempt, both logs fetched, `analyze_logs.py` found only the two
expected/benign WARNINGs (disconnect + one observe-only stall
signature during coast-down), Hall/LIN rpm agreed closely throughout.

**Second real bug, same day: the script didn't exit on its own —
needed Ctrl-C even after a fully successful run.** Root cause and fix
(`saleae_mcp/server.py`'s new `close_manager()`, called in a `finally`
block around `main()`) are documented in `saleae/CLAUDE.md`'s MCP
Server section, not duplicated here — in short, the Saleae
`automation.Manager` connection was never explicitly closed, which
kept the process alive after `main()` returned. Confirmed fixed live:
a bare connect+`close_manager()` cycle now exits promptly on its own.

## Grid Search (`run_grid.py`) — Design Settled 2026-08-21, Not Yet Built

Discussed and agreed over several rounds 2026-08-21; deliberately not
implemented yet (each round ended "nicht machen"). Named in the same
style as `run_experiment.py`/`build.sh`/`flash.sh`. Captures the design
decisions so building it next session doesn't need to re-derive them.

**3×3 stencil centered on the firmware defaults, not an arbitrary
range.** `KP`/`KI`'s current defaults (`KPDEFAULT`/`KIDEFAULT` in
`main.c`) are the grid's center, i.e. delta `(0, 0)`. The user supplies
one `p_delta` magnitude and one `i_delta` magnitude; the grid is the 9
combinations of `{-p_delta, 0, +p_delta} × {-i_delta, 0, +i_delta}`. The
center point (`0, 0`) is included automatically — that's the same
`pi 0.0 0.0` default-gains reference run already captured in
`runs/2026-08-20_134718_experiment/`, so it's directly comparable, not
a fresh baseline. A useful side effect of exactly this 3×3 shape: it
doubles as a central-difference finite-difference stencil, so it can
directly seed the gradient search's initial direction afterward, not
just serve as a coarse landscape scan.

**Reuses `run_experiment.py`'s SSH-per-point pattern, minus Saleae.**
Each of the 9 points calls `capture_step_response.py --p-delta/
--i-delta` on the Pi over SSH, the same way `run_experiment.py`'s
`_run_motor_capture()` already does — no Saleae trigger-arm/export/
plot machinery, per `analysis/CLAUDE.md`'s Cost Function section's
decision to keep the grid-search phase LIN-only. Range is (as with
`run_experiment.py`) deliberately **not** re-checked client-side beyond
"is this a number" — each of the 9 `pi <delta> <delta>` sends still
goes through the watchdog's own `validate()`, so an out-of-range
`p_delta`/`i_delta` gets rejected per-point automatically, no separate
grid-level bounds logic needed.

**Consent model: one confirmation covers the whole 3×3 sweep, not 9
separate prompts — deliberately, resolving the "doesn't scale to many
unattended runs" note from the grid-search TODO item.** Sequence, same
shape as `run_experiment.py`'s checklist: watchdog `--live` check (SSH,
automatic) → ask whether the motor power supply is on → ask for the
`p_delta`/`i_delta` magnitudes → one motor-start confirmation → then all
9 points run without further per-point prompts. This is safe specifically
*because* the user is required to physically stay at the setup with a
hand on the power supply for the whole sweep, ready to cut power
directly — matching `raspi/watchdog/CLAUDE.md`'s own philosophy that
real safety limits belong in hardware/process, not in a software
prompt's discipline. The single upfront consent is standing in for "I
will be physically present and able to intervene," not "I have reviewed
and approved all 9 specific runs."

**Ctrl-C abort, discussed but not yet implemented:**
1. `KeyboardInterrupt` (SIGINT) hits the local `run_grid.py` process;
   since the SSH call for the in-flight point runs via a blocking
   `subprocess.run()`, the local `ssh` client normally receives the
   same signal and the connection drops.
2. That disconnects `capture_step_response.py`'s connection to the
   watchdog's local socket, which triggers the watchdog's **already-
   existing** `client disconnected — stopping motor` safety behavior
   (no new code needed for this part — already observed live in
   multiple prior logs).
3. **Belt-and-suspenders addition on top of step 2:** `run_grid.py`'s
   own `KeyboardInterrupt` handler should also actively send an
   explicit `speed 0` itself (a quick separate SSH call), rather than
   relying solely on step 2's disconnect-detection timing.
4. Then log an unambiguous `ABORTED BY USER after point N/9 (P=.., I=..)`
   in `run_grid.py`'s own output — deliberately not relying on
   `watchdog.log` for this distinction, since that log's disconnect
   line looks the same regardless of *why* the connection dropped (user
   abort vs. SSH hiccup vs. a crash), so it can't tell those apart on
   its own.
   
   **Caveat, not fully resolved:** step 1→2's signal propagation over a
   plain `ssh host "cmd"` call (no pty) is the *likely*, not
   *guaranteed*, behavior — so this Ctrl-C path is a fast, convenient
   way to end the automated sweep, not the actual safety guarantee.
   The physical hand-on-power-supply requirement above is what actually
   guarantees a stop regardless of whether the software path behaves as
   expected.

**Output layout: one directory for the whole sweep, not one per
point.** Unlike `run_experiment.py` (one `runs/<timestamp>_experiment/`
per single point), `run_grid.py` writes everything from all 9 points
into a single `runs/<timestamp>_grid/` — the 9 points aren't
independent experiments, they're one sweep answering one question
("what does the P/I landscape look like around the default point"), so
one directory reflects that. Per-point files need distinguishing names
within it instead of the fixed names `capture_step_response.py`'s CSV/
log normally get, e.g. `point_p-0.10_i-0.10.csv`/`.log`,
`point_p0.00_i0.00.csv`/`.log`, ... `point_p0.10_i0.10.csv`/`.log`.
`watchdog.log` is fetched **once, after the last point**, not once per
point — it's a single continuously-appended log on the Pi, never reset
between `capture_step_response.py` invocations, so the final fetch
already contains all 9 points' traffic; fetching it 9 times would just
be 8 redundant, growing supersets of the same file.

**Summary output: a 3×3 ISE matrix.** Each point's cost (see
`analysis/CLAUDE.md`'s Cost Function section for the ISE formula) goes
into `grid_results.csv` (columns: `p_delta,i_delta,ise`) in the same
sweep directory — machine-readable input for the later gradient search
(which needs the grid's best point as its seed), plus printed as a
readable 3×3 table to the console at the end. A small heatmap PNG of
the same matrix would fit this project's existing habit of producing a
plot per experiment, but is a nice-to-have, not essential — the CSV is
the output the gradient search actually depends on.

**4-second pause between points (thermal caution + cleaner step
starts).** Discussed 2026-08-21: motivated by a concern that the power
supply could warm up over 9 back-to-back ~8s motor runs with no
automatic current-based cutoff available (current sensing is still
physically disabled, see STM32/CLAUDE.md's Known Hardware Issue) — a
fixed time-based pause is currently the only lever available for this,
same reasoning as every other time/speed-only safety limit in this
project. `INTER_POINT_PAUSE_S = 4` (module-level constant, easy to
raise later if a full sweep turns out to still run warm), inserted
between each point's `speed 0` and the next point's start. Secondary
benefit beyond thermal: it also lets the motor come to genuine
mechanical rest (not just LIN-commanded zero) before the next point
starts, so consecutive step responses don't carry over residual
momentum from the previous point's coast-down into the next point's
measurement.

**`capture_step_response.py`'s `DURATION` shortened 8.0s → 7.0s
(2026-08-21), for the same thermal-caution reasoning as the inter-point
pause above.** This is a shared-script constant, not grid-search-only —
it affects every caller (`run_grid.py`, `run_experiment.py`, direct
interactive use). Considered and rejected 6.0s: the ~2-3s
settling-to-steady-oscillation time observed so far comes only from the
firmware **default** gains (`KPDEFAULT`/`KIDEFAULT`) — the whole point
of the grid search is to test *untested* P/I combinations, and a
badly-tuned corner of the grid (e.g. too much `I`) could settle slower
or oscillate worse than the default ever has. 7.0s keeps a real margin
over what's actually been observed so far; 6.0s risked cutting off
exactly the slow-settling/growing-oscillation behavior the grid search
is supposed to catch and penalize via the ISE score. Re-shortening
further should wait until a real grid sweep's own data shows every
point (including the corners) settling well before the current 7.0s
window, not be assumed from the default-gains behavior alone.
**No change needed on the Saleae/`run_experiment.py` side:**
`_arm_trigger_capture()`'s `after_trigger_seconds=10` was already
longer than the old 8.0s `DURATION` with margin to spare, so it
comfortably covers the new, shorter 7.0s step too — the trigger pin's
own HIGH duration just shrinks by ~1s to match the shorter step,
`has_sustained_high()`'s classification (0.5s minimum) isn't remotely
close to that margin either.

**Deployed and confirmed on real hardware the same day (2026-08-21).**
`raspi/deploy.sh` run (one transient `motorpi.local` mDNS failure, its
own built-in retry succeeded on attempt 2 — the usual flakiness, not a
real problem), then verified directly on the Pi (`grep DURATION
capture_step_response.py`) before a live test run. Actual measured
duration `speed 1000` → final `speed 0`: 6.81s (35 samples × 0.2s =
7.0s `DURATION`, matches exactly). `/analyze-logs`: only the expected
`client disconnected — stopping motor` line, nothing else — cleaner
than some prior 8.0s runs, which occasionally also showed the benign
observe-only stall signature at coast-down. Step-response shape
unchanged from the 8.0s baseline: fast rise (rpm≈850 within ~0.4s),
settles into the same ~950–1025 oscillation band around the 1000
target, current stable in the same roughly -0.44..-0.59A range — the
last second that got trimmed was genuinely redundant steady-state data,
not lost information.

**First real `run_grid.py` sweep, confirmed end-to-end on real hardware
(2026-08-20, `runs/2026-08-20_145713_grid/`, deltas ±0.01 — the
smallest possible wire step, a deliberately conservative first test).**
All 9 points completed, no abort. `analyze_logs.py` across all 10 log
files (9 per-point `capture_step_response.log` copies + the one
sweep-spanning `watchdog.log`): only expected/benign findings — 9
normal `client disconnected` lines (one per point) plus one from an
earlier same-day single-point test also caught in the same
continuously-appended `watchdog.log`, 4 of the 9 points showing the
known observe-only stall signature at coast-down, and a single
one-off `rpm` call at 65ms (>50ms threshold, negligible). Confirms
`run_grid.py`'s output-layout design working exactly as specified: one
directory, 9 uniquely-named point CSV/log pairs, `watchdog.log` fetched
once at the end already covering the whole sweep.

Result — `grid_results.csv`:
```
             P=-0.01      P=+0.00      P=+0.01
I=+0.01    3,574,375    2,146,875    1,428,750  <- best
I=+0.00    2,184,375    1,573,750    1,582,500  <- center (defaults)
I=-0.01    2,275,000    1,569,375    1,673,750
```
Best point: `P delta=+0.01, I delta=+0.01` (ISE 1,428,750, vs. 1,573,750
at the untouched defaults). Pattern: `P` below the default is
consistently worse across all three `I` rows (ISE roughly 1.4-2.3x
higher) — a real, direction-consistent effect even at this smallest
possible delta step, not just noise. `I`'s effect alone is less
consistent (mixed sign depending on which `P` row), but combined with
`P+0.01` it gives the sweep's best result — an early sign of real
P/I coupling, i.e. exactly why a 2D grid (not two independent 1D
sweeps) was the right call. **Caveat: each point was measured once, no
repeats** — the direction of the P effect looks robust (same sign at
every I level), but no run-to-run repeatability check has been done yet,
so treat the exact magnitudes as provisional.

**Qualitative confirmation, same run:** the best point's rpm trace
(`best_point_p+0.01_i+0.01.png`) shows a smooth, monotonic PT1-like
("Tiefpass") rise from 0 to ~1000 over about 1s, then settles into an
even tighter ~950-1025 oscillation band than the default-gains
baseline — visibly real electromechanical (rotor-inertia) dynamics, not
a software-shaped curve, now that `updateramp(false)` is in effect (see
the `updateramp()` entry above). Good independent confirmation that
disabling the ramp was the right call for characterization.

**Repeatability check on the same ±0.01 grid, same day
(`runs/2026-08-20_151658_grid/`) — the caveat above was justified: the
two runs are only weakly related.** Quantified, not just eyeballed:
Pearson r=0.15, Spearman rank correlation ρ=0.17 between the two
`grid_results.csv`s — both close to zero, not meaningfully different
from "no relationship" at only 9 points. Mean ISE level stayed similar
between runs (ratio 0.95, so no broad drift like a slowly discharging
battery), meaning the mismatch is in each point's *relative* ranking,
not a uniform shift. The run-1 "best point" (`P+0.01, I+0.01`,
1,428,750) was rank 1 in run 1 but rank 7 of 9 in run 2 (2,017,500,
+41%) — not reproduced at all. The only part of the pattern that
survived: the two `P=-0.01` points with `I≤0` landed in the worst two
or three ranks in *both* runs. Conclusion carried into the next sweep
below: at the smallest possible delta (±0.01), measurement noise is
comparable to or larger than the real P/I effect for most of the grid.

**Soft stop confirmed on real hardware the same day
(2026-08-20, ~15:35 single-point test after deploying it).** Logged
sequence: `speed 800` → `speed 600` → `speed 400` → `speed 200` →
`speed 0`, each ~0.25s apart, 1.02s first-reduction-to-zero (target
was 1.0s) — matches `_soft_stop()`'s design exactly.
`/analyze-logs`: only the one expected `client disconnected` line, not
even the usual observe-only stall signature this time (one data point,
not yet enough to claim the softer stop reduces how often that fires).

**Second real sweep, larger delta (2026-08-20, `runs/
2026-08-20_153737_grid/`, deltas ±0.02 — deliberately larger than the
±0.01 runs above, precisely because those showed noise dominating the
signal).** All 9 points clean (`analyze_logs.py`: only expected
disconnect/stall-signature lines, no real anomalies). Result:
```
             P=-0.02      P=+0.00      P=+0.02
I=+0.02    2,172,500    1,978,750    1,770,000
I=+0.00    2,133,125    2,143,125    1,651,875
I=-0.02    3,065,625    2,153,125    1,646,250  <- best
```
**Much cleaner than either ±0.01 run: ISE decreases monotonically from
`P=-0.02` to `P=+0.02` in all three `I` rows, no exceptions.** Confirms
the "more `P` than default is better" direction seen (noisily) in both
±0.01 runs, now as a clear, consistent signal — exactly the outcome
expected if ±0.01 was genuinely too small relative to the noise floor.
Best point `P+0.02, I-0.02` (1,646,250) is nearly tied with `P+0.02,
I=0.00` (1,651,875) — once `P` is raised, the exact `I` value barely
matters at this scale. Worst point is the `P=-0.02, I=-0.02` corner
(3,065,625), clearly separated from the rest of its column. Natural
next step (not yet done): push `P` further positive (e.g. ±0.03-0.05)
to see where this trend levels off or reverses.

**Future risk, not yet a problem: `capture_step_response.py`'s
`TARGET_SPEED` (currently 1000) could change one day, and `run_grid.py`
would not notice.** `run_grid.py` has its own separate `TARGET_SPEED =
1000` constant for its ISE calculation (`_compute_ise()`), duplicated
because no shared-config file crosses the Windows/Pi boundary in this
project — same reasoning already applies to `PI_HOST`/`DEVICE_ID` etc.
being hardcoded per file. If `capture_step_response.py`'s `TARGET_SPEED`
is ever changed (e.g. to 1500) without also updating `run_grid.py`'s
copy, nothing errors — `_compute_ise()` would silently score every
point against the *wrong* setpoint, producing large, meaningless ISE
values instead of a clear failure. There is also currently no
`--target-speed` CLI flag on `capture_step_response.py` — `target_speed`
is only overridable by calling `run()` directly in Python, not through
the SSH/CLI path `run_grid.py`/`run_experiment.py` actually use, so
changing it for real would need a source edit (+ redeploy) in the first
place, same as the `DURATION` change above. Two more things that would
need re-checking, not just assumed to carry over, if the target speed
ever does change: `_soft_stop()` already scales proportionally
(`target_speed * i / steps`) so needs no fix, but `DURATION`'s "enough
margin over the ~2-3s settling time" reasoning was validated
specifically at 1000rpm — PI settling dynamics don't necessarily scale
linearly with setpoint, so that margin should be re-validated at a new
target speed rather than assumed to still hold. ISE values gathered at
different `TARGET_SPEED` settings also wouldn't be directly comparable
to each other.

**`run_grid.py` gained an automatic best-point chart (2026-08-20).**
`_make_best_point_plot()`: same rpm-step + current-twin-axis style as
`run_experiment.py`'s `_make_plot()`, but LIN-only (no Saleae/Hall
overlay, consistent with the grid search staying LIN-only throughout).
Runs automatically at the end of `main()` against whichever point had
the lowest ISE, saved as `best_p{..}_i{..}.png` in the same sweep
directory. Verified directly against the real
`runs/2026-08-20_145713_grid/` data (not just a synthetic test).

## LIN Protocol
### Header Operation
The header operation is like this:
* write a syncbyte
* read if syncbyte has been sent, compare with the write byte
* write a address with added parity
* read if byte has been sent, compare with the write byte
* The address has an associated number. The number you find in linaddresses.py. The address also tells you, if this is a pure write (master to slave), and actually a read (slave to master).

The header operation is a requirement for both reading and writing
messages. After the header, both sides look up the address: raspi in
`linaddresses.py`, the motor (STM32) in its equivalent `addresses.h`.
Both tables must agree on the same address → direction mapping — the
direction (write or read) is not chosen per-message, it's committed to by
the address itself, ahead of time, on both ends.

### Master to Slave
this is the write operation. number of bytes are sent to slave. After writing a byte, you always need to read, and compare!
A checksum is sent.

### Slave to Master
this is the read operation. number of bytes are read from slave.
Finally a checksum is received from the slave. No write/read-compare here
— the slave is the transmitter during this phase, there is nothing of
ours to echo-compare against. The write/read-compare requirement applies
to the header only.

### Slave Topology

Currently 1 motor slave, live on the bus. `addresses.json` (see below)
already reserves room for more: up to 4 motors, 2 current sensors, 2
light sensors — reserved capacity in the addressing scheme, not a claim
that this hardware exists yet. Keep the PID table structure generic
rather than hardcoded to a single slave, but don't build device
firmware/support for units that don't exist yet.

### Address Table Single Source of Truth (In Progress)

With 3+ separately hand-maintained address tables
(`raspi/control/linaddresses.py`, `STM32/`'s `addresses.h`,
`currentsensor/firmware/addresses.h`, soon `lightsensor/` too, plus
future motor slaves), manual sync is a proven bug source — the DCPS
course project's own notes (`currentsensor/notes.md`, Problems 8 & 10)
document exactly this failure mode happening once already, and it
resurfaced live in this project too: `currentsensor/firmware/addresses.h`
was still using the motor's own PIDs, with different message byte
counts for the same PID names — a real collision waiting to happen once
current-sensor hardware actually joins the bus, not just a theoretical
risk.

**Design (settled 2026-08-05):** `addresses.json` (repo root) is now the
single canonical source. `generate_addresses.py` (repo root) generates
from it:
- `addresses.md` (repo root) — human "at a glance" occupied/free PID
  map, shown block-wise (see addressing model below).
- `linaddresses.py` (the master/raspi's view) — every message across
  every device class; `sources`/`destinations` are strings (including
  `"master"`) naming a device *class*, not a fixed wire address.
- `addresses.h` — **one single file, byte-for-byte identical for every
  embedded target** (STM32, currentsensor, lightsensor, future motor
  slaves) — no per-target filtering. Message names are already globally
  unique across classes, unused `const uint8_t`s cost effectively
  nothing, and firmware already decides what to act on via PID
  comparison regardless of what else happens to be declared in the
  header. `sources`/`destinations` there use small distinct `uint8_t`
  sentinels (`master`, `motor`, `current`, `light`) mirroring the Python
  class-name strings, since C can't put strings in a `uint8_t[]` —
  each non-`master` sentinel is that class's own lowest block-base pid
  (e.g. `current` = `cntl0cur`'s pid, `0x20`), used purely as a tag in
  `sources[]`/`destinations[]` and never compared against `pids[]`.

**Addressing model — multiple identical physical units, one firmware
image each:** up to 4 motors (and multiple current/light sensors)
planned, but firmware must stay byte-identical across every unit of one
device type — so no single unit's PID can be baked in at compile time.
Instead:
- The lowest 2 ID bits of every message's PID are reserved for an
  **instance number** (0-3; only 1 bit is actually used today for
  current/light, which have 2 instances each). Message *type* occupies
  the remaining upper ID bits — every message's base PID in
  `addresses.json` is a multiple of 4 (one 4-PID "block" per message
  type). A separate `instances` list (`{"class": "motor", "num": 0,
  "id": "0x00"}`, ...) gives each physical instance's 2-bit offset.
- The actual on-wire PID for message X addressed to instance N is
  `base_pid(X) | id(N)` — computed at **runtime**, not compile time.
- Each physical board determines its own instance number at boot from
  **hardware strap pins**, not from a firmware source difference — on
  the STM32 motor controller, `PB14`/`PB15` read via internal pull-ups,
  jumper-to-GND to select (see `STM32/CLAUDE.md`'s Buttons/Switches
  section). This is what actually makes byte-identical firmware across
  multiple physical units possible.
- `addresses.md`'s block table is the "at a glance" check for this:
  which 4-PID blocks are occupied by which message type, how many
  instance slots within a block are still free, and which blocks are
  entirely free for future message types.

**Writes directly to the real consuming files** — `raspi/control/
linaddresses.py`, `STM32/firmware/Core/Inc/addresses.h`, and
`currentsensor/firmware/addresses.h` — no `generated/` staging step.
An earlier, temporary review-before-adopt phase wrote drafts to
`generated/` (gitignored) instead while the addressing scheme itself
was still being hand-reviewed; that phase ended 2026-08-06, confirmed
by `generate_addresses.py`'s own docstring. Edit `addresses.json`, then
re-run the generator — never hand-edit the generated files directly.

**Not yet done — see Open Points below**: wiring the runtime
jumper-read into actual firmware dispatch logic.


## Battery

**Open decision: 8S vs 9S (24V vs ~28.8V nominal) — not yet decided, see
Open Points below.** 9 cells were ordered (1 originally as a spare), and
9S has been evaluated as viable (BMS supports 8S–20S; motor's 36V max
comfortably covers 9S's ~32.9V full-charge; the Victron buck converter's
36V input rating covers it too) — but no final call has been made yet.
Text below describes 8S/24V as that's the current bench setup's
voltage (per `STM32/notes.md` "Betriebsbedingungen") — treat any "24V"
below as provisional, not a settled spec, until this is decided.

8 Batteries (9 ordered, 1 as spare unless 9S is chosen):
* REPT CB56 - 100Ah - LiFePO4 3.2V - Grade A

100Ah (~2.56kWh) is intentionally sized for future mobile use, not just
the current bench-test phase — don't read it as oversized/a mismatch for
the test rig.

1 BMS:
* JK Smart Active Balance BMS BD6A20S8PR - (8S - 20S) - 80A - LiFePO4 / Li-ion

Note: 8S1P LiFePO4 is nominally ~25.6V (8 × 3.2V), commonly labeled
"24V" as a class, but actual pack voltage swings roughly 29V (full) to
20V (near empty) across a discharge cycle — it is not a fixed 24V. Since
motor no-load speed scales with voltage (~105 RPM/V, see
`STM32/CLAUDE.md`), this voltage swing is a plausible confound for the
open "does `speed` really mean RPM?" question below, separate from the
LIN `speed` parameter itself.

## Buck Converter
The Buck converter convers 24V from the battery to 12v. The Raspi itself has a shield, which converts 12V to 5V.
This 7A/60W converter only powers the Raspi's logic — the motor draws
directly off the 24V battery, not through this converter (a 1000W motor
obviously can't run through a 60W supply).

Buck Converter
* Victron Orion-Tr 24/12-5


# Safety

Cross-cutting — applies regardless of concept/architecture changes.

- **The watchdog on the Raspi (`raspi/watchdog/`) is independent of the
  optimization loop and of Claude Code.** It runs as its own process and
  stops the motor on its own if, e.g., no heartbeat/command arrives for
  too long. Limits (max speed, etc.) belong in the code, not in prompts
  or Claude-side discipline.
- **Current sensing is currently physically disabled** on the STM32
  board — the current-sense shunt blew and was bridged with a copper
  wire (see `STM32/CLAUDE.md`). Any safety limit that assumes current
  measurement is available does not work right now; only time/speed-based
  limits are actually enforceable.
- A manual emergency-stop path must be triggerable at any time,
  independent of the loop.

# Open Points / Still To Be Clarified

Living tracker — remove items once resolved.

- **8S vs 9S battery decision** (24V vs ~28.8V nominal) — not yet
  decided. See Battery section above.
- **`addresses.json`/`generate_addresses.py`** — design settled and
  built (2026-08-05), writes directly to every consuming file since
  2026-08-06 (no more `generated/` staging), see LIN Protocol "Address
  Table Single Source of Truth" section above. Remaining concrete step:
  - Wire the actual runtime jumper-read (`PB14`/`PB15` → instance
    number → `base_pid | id`) into STM32 `main.c`'s LIN dispatch logic
    — the jumper *reading* itself is hardware-confirmed working
    (2026-08-05), but the dispatch logic still uses the old flat,
    single-motor constants.
  - Same runtime treatment needed in `currentsensor`/`lightsensor`
    firmware once they're built for multiple physical units.
- Saleae-specific open points (pin mapping, sample rate) — see
  `saleae/CLAUDE.md`.
- Analysis-specific open points (cost function/metric weighting) — see
  `analysis/CLAUDE.md`.
- **`speed` ≈ `rpm`, confirmed live (2026-08-04) — no longer just
  assumed.** `raspi/control/validate_speed.py` (0 → 400 → 800 → 1200 →
  800 → 400 → 0 → -400 → -800 → -1200 → -800 → -400 → 0, `rpm` checked
  after every step) ran clean end to end: `rpm` tracked `speed` to
  within roughly ±6% at every step (e.g. 400→450, 800→825, 1200→1175,
  -1200→-1200, back to 0→0), both directions, ramp up and back down.
  Good enough to treat `speed`≈`rpm` as validated for now.
  **Independent ground truth done (2026-08-17/18):** a real Saleae
  Hall-edge capture during a live `capture_step_response.py` run,
  converted to rpm via `analysis/hall_rpm.py`, tracks LIN `rpm` closely
  across ramp-up/steady-state/coast-down — see `analysis/CLAUDE.md`'s
  Hall-Edge RPM Conversion section. This *is* the independent
  measurement the validate_speed.py run above couldn't provide on its
  own. Along the way, found and explained a genuine small systematic
  bias in LIN `rpm` itself (~3.4%, from `TIM4`'s prescaler giving a
  ~1.024ms tick instead of exactly 1ms — see `STM32/CLAUDE.md`'s RPM
  Measurement Resolution section) — since fixed in firmware
  (`Prescaler=63999`). **Still not done:** explicitly controlling for
  battery-voltage drift (see Battery section above) across a longer
  run/discharge cycle.
