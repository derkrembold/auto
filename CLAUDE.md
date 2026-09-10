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

## Two-Motor Vehicle Architecture (Planned)

**Everything in this section is planned, not built — ideas from a
2026-09-07 design session (originally written up as a standalone
`BLDC_System_Specification.md`, folded into this file and its
subsystem `CLAUDE.md`s the same day, then deleted — see git history
for the original wording if needed). Subject to change as design
continues; don't treat this the way the rest of this file's "built and
confirmed" material is treated.** Mid-term priority — the user's own
framing: solve the urgent near-term problems (kickstart reliability,
see `STM32/CLAUDE.md`'s Open Points) before this hardware work starts.

The long-term target: two BLDC motors (same Bosch 1000W/24V motor as
today's single bench motor), one STM32H743 controller each
(`STM32_A`→left, `STM32_B`→right), driving a vehicle via differential
drive (steering from left/right speed difference, no separate steering
mechanism). A Raspberry Pi is the central hub — joystick input, safety
supervision, sensor fusion, eventually autonomous navigation (see Long-
Term Roadmap below).

```
Joystick → Pi → STM32_A → Motor Links
                STM32_B → Motor Rechts
```

Planned hardware additions: a second motor+controller (identical to
today's, addressed via the existing multi-instance LIN scheme — see
LIN Protocol section above, `addresses.json` already reserves room for
up to 4 motors, this would be the first time a second one actually
exists); an **external current-sensor module** for both motors over
LIN — a *different* device than the STM32's own internal current
sense, which stays physically disabled on today's board (see
`STM32/CLAUDE.md`'s Known Hardware Issue) — not yet decided whether
this reuses the existing `currentsensor/` LIN-slave design or is a new
one; an **IFM sensor suite** (own Ethernet controller, MQTT or direct
IP — TBD) — O3D depth camera (front, obstacle detection), 4x LiDAR
(side, precise/long-range), 4x ultrasonic (side/rear, wide-angle near-
field, backup for the O3D in direct sunlight); the Pi as a WiFi access
point (phone SSH/browser, Bluetooth joystick, Ethernet to the IFM
controller, LIN to both motors + current-sensor module).

**Planned STM32-side redesign** (pulse/reset/status protocol, kickstart
algorithm): see `STM32/CLAUDE.md`'s Commutation & Control section.

**Planned Pi-side redesign** (multi-process architecture, stall/
stiction response building blocks, ML-driven recovery, logging
database, web UI): see `raspi/watchdog/CLAUDE.md`. **Deliberately not
a from-scratch redesign** — the user wants to keep as much of the
existing, proven watchdog/`motorcontrol.py` architecture as possible
and build additively; the actual redesign happens interactively
between the user and Claude Code as it's built, not by following this
plan mechanically.

## Repo Structure

```
Auto/
├── addresses.json          Single source of truth for LIN PIDs (see LIN Protocol section)
├── generate_addresses.py   Generates addresses.md + writes directly to every consuming file
├── addresses.md            Generated "at a glance" occupied/free PID map
├── run_experiment.py       Standalone P/I grid/gradient-search point runner (see raspi/CLAUDE.md)
├── run_grid.py             3x3 P/I stencil sweep around the firmware defaults (see Grid Search section)
├── run_grid_row.py         One 9-point line along a single P/I axis (see Row Search section)
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

## Grid Search (`run_grid.py`)

**The P/I search is concluded (2026-09-10).** `KPDEFAULT`/`KIDEFAULT`
in `main.c` were moved `0.15`→`0.19` / `0.4`→`0.44` (the heatmap's
`P+0.04 / I+0.04` point), flashed, and validated (~27% better ISE than
the old default, no audible roughness, repeatability confirmed). No big
jumps — the honest outcome, since run-to-run noise is comparable to the
effect and nothing has been tested under the eventual ~50kg vehicle
load. **The far more valuable results of that 2026-09-07 → 09-10 arc
were elsewhere** — a permanent-hang LIN/UART bug found and fixed,
end-to-end stall detection + recovery, a reproducible Mittelrast test
case, the `reset`/`status`/`burst` protocol additions, and a MOSFET
failure turned into a documented safety envelope. **See
`analysis/grid_search_log.md`'s "2026-09-10 — P/I search concluded"
entry and its "Fazit" for the full picture.** `run_grid.py`/
`run_grid_row.py` themselves stay available for any future sweep (e.g.
once real load testing is possible).

Design/mechanics only — this section is stable and rarely changes.
**Real-hardware results (every sweep run so far, matrices, findings,
outliers, reproducibility checks) live in `analysis/grid_search_log.md`
instead, as a growing chronological log — check there for "what has the
grid search actually found," not here.** Design settled over several
rounds 2026-08-21 (each round ended "nicht machen" at the time), built
and confirmed 2026-08-20/22, deployed. Named in the same style as
`run_experiment.py`/`build.sh`/`flash.sh`.

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

**Ctrl-C abort — implemented:**
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

**Summary output: a 3×3 ISE matrix, plus MSSD roughness matrices
(added 2026-08-25).** Each point's cost (see `analysis/CLAUDE.md`'s
Cost Function section for the ISE formula) goes into `grid_results.csv`
(columns: `p_delta,i_delta,ise,mssd_2s,mssd_full`) in the same sweep
directory — machine-readable input for the later gradient search
(which needs the grid's best point as its seed), plus all three
printed as readable 3×3 tables to the console at the end. A small
heatmap PNG of the same matrix would fit this project's existing habit
of producing a plot per experiment, but is a nice-to-have, not
essential — the CSV is the output the gradient search actually depends
on. The "best point" selection (for the automatic chart below) still
uses ISE only, not MSSD.

**MSSD (Mean Square Successive Difference, von Neumann 1941) — a
second metric alongside ISE, added 2026-08-25, because ISE alone can't
tell a smooth rise from a rough/hunting one that happens to reach the
same target equally well.** Found by ear/eye first (a `P+0.10, I+0.03`
step-response trace visibly and audibly hunted up and down during the
first second, e.g. `rpm` going 575→800→650→950→750→950 within ~1s),
then quantified: `_compute_mssd(csv_path, window_s)` is the mean of
`(rpm[i+1]-rpm[i])²` over consecutive samples in a window — squared,
not a plain absolute-difference sum, specifically because a linear sum
scores "one violent single reversal" the same as "many small even
wobbles" of similar total size, and a real comparison (`P+0.10, I=0.00`
vs `P+0.10, I=-0.03`) showed exactly that failure mode: only ~14%
apart on a linear sum despite one having a visibly sharper single
double-reversal, but ~2.2x apart once squared — matching the actual
audible/visible difference far better. Same quadratic-penalty
philosophy as ISE itself (which already squares distance-from-target
for the same reason: punish large deviations disproportionately).
Mean, not sum, so results stay comparable in magnitude across windows
covering a different number of samples. Two windows, both requested by
the user: `mssd_2s` (`MSSD_SHORT_WINDOW_S = 2.0`, the rise/transient
phase specifically) and `mssd_full` (the whole 7s capture, where every
point's normal steady-state ripple also contributes, not just the
rise). See `analysis/grid_search_log.md`'s 2026-08-25 section for the
real traces and numbers that prompted this, including the earlier,
rejected linear-sum "Total Variation" version and why it wasn't good
enough on its own.

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
close to that margin either. Confirmed deployed and working on real
hardware the same day — see `analysis/grid_search_log.md`'s 2026-08-20
entries for the measured duration and step-response shape.

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

## Row Search (`run_grid_row.py`) — Built 2026-08-25

A sibling to `run_grid.py`, for when a 3×3 stencil isn't the right
shape — one line of 9 points along a single P/I axis, the other axis
held fixed, instead of a symmetric 2D grid. Motivated by the same-day
finding that a 3×3 grid couldn't easily reveal *where* the P trend
actually turns over (see `analysis/grid_search_log.md`'s 2026-08-25
section) — a wide, densely-sampled line along one axis gives that
directly, without needing to re-guess a bigger delta and rebuild a
whole new grid each time.

**Mechanics: imports `run_grid.py` as a module and reuses its SSH/
point-execution/ISE/MSSD/plotting machinery directly, not duplicated.**
`run_grid.py` itself was lightly refactored to make this possible —
`_fetch_watchdog_log()` and `_run_analyze_logs()` were pulled out of
its `main()` into standalone functions specifically so `run_grid_row.py`
could call them too, with identical behavior in `run_grid.py` itself
verified unchanged (compiles, no logic moved into different order).

**One row = one axis varying, the other fixed, 9 points always
symmetric around delta=0** (`-4·step, -3·step, ..., 0, ..., +4·step`)
— matches the "0 = current firmware default" convention `run_grid.py`
already uses. `axis` ("p" or "i"), the fixed value for the other axis,
and the step size are all required arguments (CLI or interactive
prompt) — no built-in default step, deliberately, same reasoning as
`run_grid.py` never assuming a default delta magnitude.

**`P_DELTA_MAX_DEFAULT = 0.10` — a hard, client-side safety cap unique
to this script, checked before any motor movement, on every point's `P`
value regardless of whether `P` is the row's fixed or its varying
axis.** This is deliberately *not* handled the way `run_grid.py`/
`run_experiment.py` handle the wire-level P/I range (left entirely to
the watchdog's own `validate()`, never duplicated client-side) — the
watchdog has no way to know about this limit, since it isn't a
hardware/protocol constraint at all. It's tool-specific policy from
this project's own experience: `P delta≈0.10` is where audible motor
roughness ("Ruppeln") was first found and where the user drew an
explicit line ("da werden wir niemals hingehen" about going further —
see `analysis/grid_search_log.md`'s 2026-08-25 section). A named,
overridable constant rather than a hardcoded rule ("sag niemals nie") —
may need to change later (e.g. once tested under load), but defaults to
enforcing today's known boundary, and fails loud with a clear message
before touching the motor if violated.

**Consent model: one confirmation per row, and the script exits when
the row finishes — no automated chaining across rows.** Same physical-
presence reasoning as `run_grid.py`'s whole-sweep consent, just applied
to the smaller 9-point unit. For another row (e.g. a different fixed
value), the user re-runs `run_grid_row.py` manually, with a fresh
consent — explicit user design choice: "Ein Bestätigung ist ein 9
Punkte Lauf. Dann wird beendet. Dann starte ich `run_grid_row` von
neu." Deliberately keeps every single run small enough that an abort
mid-row costs almost nothing to redo, rather than growing rows to
cover more of the P/I plane in one sitting.

**Output: `runs/<timestamp>_row/grid_results.csv`, same column schema
as `run_grid.py`'s** (`p_delta,i_delta,ise,mssd_2s,mssd_full`) —
deliberately identical, so multiple rows (and grids) from different
sessions can later be merged by `analysis/grid_heatmap.py` (see
`analysis/CLAUDE.md`) without any format translation. Per-point CSV/
log naming and the automatic best-point chart are unchanged from
`run_grid.py`, just printed as a 1D list (`_print_row()`) instead of a
2D matrix, since a single row has no second axis to lay out.

**Future idea, explicitly not being built now: `run_grid_column.py`.**
Raised in discussion as a possible companion — but the current `axis`
parameter already covers both orientations (P varying/I fixed, or I
varying/P fixed) through the same script, so a dedicated "column"
script would only be a naming/ergonomics change (two fixed scripts
instead of one parameterized one), not new capability. Worth
reconsidering only if the `axis` parameter turns out confusing in
practice — not a design gap today.

## Candidate Selection Philosophy — `P` As High As Practical, `I` Only As High As Needed

**Decided 2026-08-25, by discussion, not yet applied to an actual final
choice.** Governs how a final `KP`/`KI` candidate should eventually be
picked from the grid data — not a `run_grid.py` mechanics decision, but
a control-engineering judgment call that sits downstream of it.

**Why `I` can't just be minimized: the plant itself already contains an
integrator** (`ω = ∫(torque − load)/J dt`), so a pure-P controller left
with a constant added load torque settles at a nonzero steady-state
speed error (`error = load / Kp` — classic droop behavior, the same
effect seen on droop-controlled generators). Only the controller's own
`I` term removes this. The project's actual near-term context makes
this concrete, not hypothetical: today's bench load is just the motor's
own wheels + gearbox, but the eventual vehicle adds roughly another
50kg — a load increase that will make steady-state droop from an
under-tuned `I` much more noticeable than it is on the current rig.
**So `I` should not be tuned toward zero for "robustness" — that
reasoning was considered and rejected.**

**Why `I` also shouldn't be pushed to the aggressive edge of what looks
best under today's no-load bench test.** A larger `I` reduces phase/
stability margin, and that margin loss gets worse specifically as plant
dynamics change (higher inertia from added load) — a gain combination
that looks merely lively under the current light load could become
properly unstable or oscillatory once the vehicle's mass is added,
since the `KP`/`KI` pair was never tested under anything like that
load. This is exactly what the MSSD roughness metric (see above) is
already starting to show even under today's light load: `P+0.10,
I=0.00` measurably rougher than `P+0.10, I=-0.03` — a preview of the
same kind of degradation load would likely make worse.

**The resulting principle: `I` only as high as needed to keep
steady-state droop acceptable under the expected future load, with
deliberate margin below whatever level looks most "optimal" (lowest
ISE) on the current unloaded rig.** Practical consequence for picking
a seed/final candidate out of the grid data: prefer a point from the
lower-`I` side of whatever good region the search finds, not
automatically whichever single point scored the lowest no-load ISE —
the good region found so far (`P≈0.05..0.10, I≈0.00..0.03`, see
`analysis/grid_search_log.md`) is fairly flat, so this costs little to
nothing under today's test conditions while buying real margin for the
load that hasn't been tested yet. Testing under a more realistic load
(even an approximate one — extra inertia/friction on the bench, not
necessarily the real vehicle) before finalizing anything remains the
more direct fix; this principle is what to do in the meantime, while
that isn't available yet.

**`P` design principle, same discussion: prefer `P` as high as practical
within the good region, bounded by no-load MSSD staying acceptable —
unlike `I`, no deliberate margin needed below the best-looking value.**
Derived from the same linearized 2nd-order model as the `I` principle
above: for `J·dω/dt + B·ω = T − load` under PI control, the closed-loop
damping ratio works out to `ζ = (B+Kp) / (2·√(J·Ki))`. Two things fall
out of this directly: `J` (inertia, grows with the eventual vehicle
load) sits in the denominator, so **added load reduces damping for any
fixed gains** — the system gets more oscillation-prone under load,
independent of tuning. But `Kp` sits in the numerator, additively with
the plant's own friction `B` — **so a higher `Kp` directly buys back
damping margin against exactly that load-driven loss**, while `Ki`
(denominator only, no compensating numerator term) purely erodes it.
`P` and `I` are thus mirror images here: more `P` builds load-robustness
margin, more `I` spends it.

**Cross-checked against the real 2026-08-25 MSSD data, not just the
model:** in 2 of the 3 tested `I` rows, `MSSD_2s` fell as `P` rose from
-0.10 to 0.00 to +0.10 (less roughness with more `P`, matching the
model). The one exception (`I=0.00`: high at both `P` extremes, lowest
at the center) is exactly the point already flagged as the *least*
reproducible in the whole dataset (a +50% swing between the two ±0.10
repeats) — read as likely noise, not a real counter-effect, though not
proven either way yet.

**Practical consequence: unlike `I`, `P` does not need to be pulled back
from the best-looking value for load-safety reasons — if anything, more
`P` is protective as load increases.** The only ceiling on `P` is
no-load smoothness itself: push `P` as high as the good region allows
while `MSSD` (both windows) stays at a level the user is willing to
accept hearing on the bench today, since that's the one hard constraint
this whole exercise started from — see the note below on what "accept"
currently means in practice.

**Net effect on how ISE factors into candidate selection: the
de-emphasis of ISE described above applies specifically to the `I`
axis, not to `P`.** For `P`, "as high as practical" and "lowest ISE"
point the same direction in every sweep run so far (`P` above default
has been the single most consistent finding across the whole grid
search) — there's no real tension to resolve there, `MSSD` just acts as
the practical ceiling on how far to push it. The place ISE is
genuinely overridden by a non-ISE criterion is `I`, where the
lowest-ISE value and the load-safe value are not the same point.

**Open caveat on `MSSD` itself, explicitly acknowledged, not yet
resolved: the whole point of this metric is to proxy for something the
user can hear** — "ich will einfach kein Ruppeln hören, auch ohne
Last" (2026-08-25) is the actual requirement; `MSSD` is only a
stand-in for it. So far `MSSD` has been calibrated against exactly
**one** real ear-confirmed event (the original `P+0.10, I+0.03` trace
that started this whole investigation) — everything since (the
`I=0.00` vs. `I=-0.03` comparison, the theoretical cross-check above)
has been visual/numeric reasoning built on that single anchor, not a
second independent by-ear confirmation. **Correlation between `MSSD`
and actually-audible roughness is plausible but not yet proven.**
Practical fix, not yet started: on future real motor runs, explicitly
note by ear whether a run sounded rough or not, and check that against
the computed `MSSD` — a handful of paired observations would turn this
from "plausible proxy" into either a trusted one or a metric that needs
rethinking.

**Related, same discussion: this is also part of why a classic small-
step gradient search was judged a poor fit for the next phase (see
`analysis/grid_search_log.md`'s 2026-08-25 section) — finite-difference
gradient estimates get noisier as the step shrinks (already measured:
±0.01 gave ~zero repeat-to-repeat correlation, ±0.02-0.03+ gave good
correlation), so a literal gradient descent would tend to chase noise
exactly in the fine-tuning regime it needs to be most careful in. Not
worth over-optimizing a fragile local optimum on the unloaded rig in
the first place, given it may not even transfer to the loaded vehicle.**

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

**STM32 side done** (confirmed in `main.c` 2026-09-10): `hwbits` is
read from `PB14`/`PB15` at boot and all four `cntl*mot` dispatch
branches compare against `cntl*mot | hwbits`, with the index lookup
masking `& 0x3c` (instance-agnostic message-type match) and a separate
`& 0x03 == hwbits` instance check. Still open for `currentsensor`/
`lightsensor` firmware — see Open Points below.


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

## Long-Term Roadmap (Planned)

**Explicitly far future — "Zukunftsmusik" in the user's own words
(2026-09-07) — direction confirmed correct, no near-term commitment,
sequenced well after the Two-Motor Vehicle Architecture section
above.** Captured here so the destination stays visible while nearer-
term work (kickstart reliability, the two-motor build-out) happens
first.

- **GPS navigation**: a GPS module on the Pi (or a phone's GPS), point-
  to-point destination entry via the web UI (see
  `raspi/watchdog/CLAUDE.md`'s planned Webserver process).
- **Odometry**: `rpm × wheel circumference × time` per motor →
  relative motion; steering direction from the left/right `rpm`
  difference (differential drive); position by integrating over time.
- **Sensor fusion (Kalman filter)**: GPS alone is coarse (3-10m error,
  ~1Hz) and odometry alone drifts unbounded — combining them (ROS's
  `robot_localization` package, already-implemented Kalman filter,
  just needs configuring) lets GPS correct odometry drift and odometry
  fill GPS gaps.
- **Obstacle avoidance via ROS**: IFM ultrasonic/LiDAR/O3D data feeds a
  ROS costmap; `move_base` handles both global path planning (A→B) and
  local obstacle avoidance, both off-the-shelf ROS capability, not
  custom-built.
- **Full ROS integration**: ROS on the Pi once joystick control is
  stable and GPS/autonomy is actually wanted — `joy` node (Logitech
  controller), `robot_localization` (Kalman filter), `move_base`
  (navigation), the watchdog itself becoming a ROS node, an IFM-to-ROS
  bridge (`sensor_msgs/PointCloud2` for the O3D, `sensor_msgs/Range`
  for LiDAR/ultrasonic), and the STM32 LIN link as its own ROS node.
  Topics: `/cmd_vel`, `/odom`, `/gps`, `/scan`, `/lidar`, `/ultraschall`,
  `/rpm`, `/current`.
- **Migration phases** (the user's own framing): Phase 1 (current) —
  joystick control, watchdog, stall/stiction response. Phase 2 — GPS,
  odometry, web UI with a map. Phase 3 — ROS, Kalman filter, A→B
  navigation. Phase 4 — autonomous driving, obstacle avoidance, full
  ROS integration.

# Safety

Cross-cutting — applies regardless of concept/architecture changes.

- **The watchdog on the Raspi (`raspi/watchdog/`) is independent of the
  optimization loop and of Claude Code.** It runs as its own process and
  stops the motor on its own if, e.g., no heartbeat/command arrives for
  too long. Limits (max speed, etc.) belong in the code, not in prompts
  or Claude-side discipline.
- **The STM32's own on-board current sensing is physically disabled** —
  the current-sense shunt blew and was bridged with a copper wire (see
  `STM32/CLAUDE.md`). The **separate LIN current-sensor board**
  (`currentsensor/`) does work, and as of 2026-09-10 the watchdog acts
  on it: an overcurrent hard stop at 15A (see
  `raspi/watchdog/CLAUDE.md`'s Two-Layer Safety Check). That's a
  *sustained*-overcurrent backstop with ~1-3s reaction, not a fast
  transient crowbar — a millisecond-scale spike still isn't catchable,
  so magnitude/design limits still matter. The subtler
  current-while-rpm-0 stall signature is still observe-only.
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
  - STM32 `main.c` LIN dispatch: **done** (confirmed 2026-09-10) —
    `hwbits` read from `PB14`/`PB15` at boot, all four `cntl*mot`
    dispatch branches compare `cntl*mot | hwbits`, index lookup masks
    `& 0x3c`, separate `& 0x03 == hwbits` instance check.
  - Same runtime treatment still needed in `currentsensor`/
    `lightsensor` firmware once they're built for multiple physical
    units.
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
