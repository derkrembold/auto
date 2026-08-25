# Grid Search — Experiment Log

Chronological record of every real `run_grid.py` sweep (and directly
related single-point real-hardware tests) run so far. Split out of root
`CLAUDE.md`'s Grid Search section on 2026-08-24 once that section grew
into a running lab-notebook of results — the design/mechanics of
`run_grid.py` itself (3×3 stencil, consent model, output layout, ISE
formula, Ctrl-C abort, `TARGET_SPEED` duplication risk, etc.) stays
there, since that's stable and rarely changes; this file is the
opposite — append-only, one entry per real run, expected to keep
growing. See root `CLAUDE.md`'s Grid Search section first for what
each of these runs is actually testing and why.

## 2026-08-20

**`DURATION` shortened 8.0s → 7.0s — deployed and confirmed on real
hardware.** `raspi/deploy.sh` run (one transient `motorpi.local` mDNS
failure, its own built-in retry succeeded on attempt 2 — the usual
flakiness, not a real problem), then verified directly on the Pi
(`grep DURATION capture_step_response.py`) before a live test run.
Actual measured duration `speed 1000` → final `speed 0`: 6.81s (35
samples × 0.2s = 7.0s `DURATION`, matches exactly). `/analyze-logs`:
only the expected `client disconnected — stopping motor` line, nothing
else — cleaner than some prior 8.0s runs, which occasionally also
showed the benign observe-only stall signature at coast-down.
Step-response shape unchanged from the 8.0s baseline: fast rise
(rpm≈850 within ~0.4s), settles into the same ~950–1025 oscillation
band around the 1000 target, current stable in the same roughly
-0.44..-0.59A range — the last second that got trimmed was genuinely
redundant steady-state data, not lost information.

**First real `run_grid.py` sweep, confirmed end-to-end on real hardware
(`runs/2026-08-20_145713_grid/`, deltas ±0.01 — the smallest possible
wire step, a deliberately conservative first test).** All 9 points
completed, no abort. `analyze_logs.py` across all 10 log files (9
per-point `capture_step_response.log` copies + the one sweep-spanning
`watchdog.log`): only expected/benign findings — 9 normal `client
disconnected` lines (one per point) plus one from an earlier same-day
single-point test also caught in the same continuously-appended
`watchdog.log`, 4 of the 9 points showing the known observe-only stall
signature at coast-down, and a single one-off `rpm` call at 65ms (>50ms
threshold, negligible). Confirms `run_grid.py`'s output-layout design
working exactly as specified: one directory, 9 uniquely-named point
CSV/log pairs, `watchdog.log` fetched once at the end already covering
the whole sweep.

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
`STM32/CLAUDE.md`'s Commutation & Control section). Good independent
confirmation that disabling the ramp was the right call for
characterization.

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

**Soft stop confirmed on real hardware (~15:35, single-point test after
deploying it).** Logged sequence: `speed 800` → `speed 600` →
`speed 400` → `speed 200` → `speed 0`, each ~0.25s apart, 1.02s
first-reduction-to-zero (target was 1.0s) — matches `_soft_stop()`'s
design exactly. `/analyze-logs`: only the one expected `client
disconnected` line, not even the usual observe-only stall signature
this time (one data point, not yet enough to claim the softer stop
reduces how often that fires).

**Second real sweep, larger delta (`runs/2026-08-20_153737_grid/`,
deltas ±0.02 — deliberately larger than the ±0.01 runs above,
precisely because those showed noise dominating the signal).** All 9
points clean (`analyze_logs.py`: only expected disconnect/stall-
signature lines, no real anomalies). Result:
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
next step: push `P` further positive (e.g. ±0.03-0.05) to see where
this trend levels off or reverses — picked up 2026-08-22 below.

## 2026-08-22

**First test of the motor on battery power instead of the transformer**
(motor only — the Pi itself was still on its usual supply this time,
see 2026-08-24 below for the first fully-battery test), single-point
`capture_step_response.py` at default gains — no CSV saved live (see
`raspi/CLAUDE.md`'s gotcha entry on this), but reconstructed from
`capture_step_response.log`'s timestamped command/reply pairs. Step
response at `speed 1000` was practically indistinguishable from prior
transformer-fed runs at the same defaults: fast rise (rpm≈700 within
~0.3s, ~875 by ~0.7s), same ~950-1025 steady-state oscillation band,
current in the same familiar ~-0.44..-0.59A range. The staged soft stop
also fired cleanly (`speed 800→600→400→200→0`, ~1s). No sign that
battery power alone degrades step-response behavior at this target
speed — see the ±0.03 grid sweep below, though, for a case (different
target: a low manual `speed 200`, plus a stiction/overshoot event at
one grid point) where battery-specific effects may or may not have
played a role.

**Separate manual `speed 200` test (via `motorcontrol.py`), same
session:** motor was slow to respond, and the watchdog's own
`_check_stall()` fired autonomously, stopping the motor ~10s *before*
the user's own manual `speed 0` landed — a good real confirmation the
self-polling stall-detection design works as intended, reacting faster
than the human at the controls with no client action needed to trigger
it (see `raspi/watchdog/CLAUDE.md`'s Two-Layer Safety Check section for
the full confirmation writeup). Whether the slow start itself was
battery-specific or just this speed being close to the motor's
breakaway/static-friction threshold was not investigated further.

**Third sweep, first time on battery power for the motor
(`runs/2026-08-22_121201_grid/`, deltas ±0.03, following up on the
"push P further" note from 2026-08-20 above) — one point contaminated
by an apparent stiction/overshoot event, rest of the sweep clean.**
`analyze_logs.py`: only expected/benign findings across all 9 points.
Result:
```
             P=-0.03      P=+0.00      P=+0.03
I=+0.03    2,346,250    1,838,125    2,045,000
I=+0.00    2,131,250    2,229,375    6,366,250  <- contaminated, see below
I=-0.03    2,276,875    2,061,875    1,920,625
```
**`P+0.03, I=0.00`'s CSV shows a genuine outlier, unlike every other
point in this sweep:** `rpm` stays at exactly 0 for the first ~800ms
after the step (all 8 other points start moving within 200-600ms),
then jumps straight to 2100 — more than double the 1000 target — while
`current_val1`/`val2` spike to -1.32A/-1.17A (vs. the usual
~-0.44..-0.59A steady-state range seen everywhere else). Settles into
the normal ~950-1050 band within another ~3s, same as any other run.
Plausible mechanism discussed: static friction/stiction held the rotor
still for ~800ms while the PI controller (particularly its integral
term) kept accumulating against a persistent large error, so when the
rotor broke free it overshot hard on the accumulated correction. This
single point's ISE (6,366,250) is roughly 3x any other point in the
sweep and should be treated as contaminated, not a real reading of
`P+0.03, I=0.00` as a gain combination — with it excluded, the ±0.03
sweep doesn't show as clean a monotonic `P` trend as the ±0.02 sweep
above, consistent with battery-vs-transformer comparisons needing
care, and/or ±0.03 simply being large enough to expose friction/
stiction effects ±0.02 didn't.

**Open question raised in discussion at the time: is the 2100 reading a
real (if brief) mechanical overshoot, or a Hall-edge-count artifact
from the unusually large current transient?** (Resolved in practice by
the repeat sweep immediately below — kept here for the reasoning.)
`rpm` is `RPMFACTOR (25) × hallCounter` counted over a 100ms window —
2100 implies 84 counted edges in that window vs. 40 at a normal steady
1000rpm, roughly 2x. `analysis/CLAUDE.md`'s Hall-Edge RPM Conversion
section already documents ~100ns EMI spikes on the Hall lines during
MOSFET commutation that inflate a *naive, undebounced* raw-capture edge
count by roughly 3.5x — the firmware's own `hallCounter` isn't
software-debounced (relies on the GPIO's hardware Schmitt-trigger
hysteresis instead), which normally suffices but might not under a
current transient this much larger than usual. Not distinguishable
from the LIN `rpm` reading alone — a Saleae capture of a reproduction
would settle it via `analysis/hall_rpm.py`'s debounced ground truth,
but see below: the event didn't reproduce on an immediate repeat, so
this was deprioritized rather than chased down.

**Additional hypothesis for the initial ~800ms stall itself, raised
2026-08-25 (three days after the original event): a Hall-sector
boundary rest position, not just PI integral windup.** The PI-windup
explanation above only ever covered *why the overshoot was so large*
once the rotor broke free — it never explained *why the rotor stayed
essentially motionless for ~800ms* in the first place. Proposed
mechanism: this firmware's 6-step trapezoidal commutation
(`driveStep()`/`driveState()`, see `STM32/CLAUDE.md`'s Commutation &
Control section) maps each of the 6 Hall states to one fixed MOSFET
configuration intended to produce torque across roughly a 60°
electrical sector — but torque within that sector isn't flat, it's
weakest near the sector's edges. If the rotor happens to come to rest
exactly at such a boundary when commanded to start, the *currently
active* commutation state could provide very little starting torque
right at that instant, even though the *next* Hall state (one more
transition away) might sit much more favorably. That would produce
exactly the observed pattern: an extended near-standstill (weak/
near-zero torque holding the rotor in place) while the PI integral
term keeps accumulating against the persistent error, followed by a
large jump once enough torque builds up (or a small mechanical
perturbation crosses the Hall boundary) to finally move into a
better-torque state — the two mechanisms (boundary position + integral
windup) working together, not competing explanations.

**User's own assessment: this event is believed to be rare, not a
systematic problem with any particular P/I combination** — happens
occasionally regardless of gains, consistent with it being about
*where the rotor happens to stop*, which is essentially random from
run to run, not a property of `P+0.03, I=0.00` specifically (matches
the "did NOT reproduce" finding directly below). **A concrete way to
check this hypothesis if/when the event recurs: a Saleae capture of the
Hall channels during the stuck period** would show directly which Hall
state the rotor was resting in, and whether that state's expected
commutation torque near its sector boundary is weak enough to explain
the stall — the same capture would also settle the still-open "is the
2100 reading real or an EMI-count artifact" question above in one
shot. **Strategy for handling this (e.g., detecting/mitigating it, or
just tolerating it as rare noise) deliberately deferred, not decided
here** — noted only as a mechanism hypothesis for now.

**Fourth sweep, same day, same ±0.03 deltas, repeated on impulse
(`runs/2026-08-22_122821_grid/`) — the stiction/overshoot outlier above
did NOT reproduce, and once it's excluded the two ±0.03 sweeps agree
reasonably well.** All 9 points started normally this time (every point
moving within 200-900ms, including `P+0.03, I=0.00` itself — no repeat
of the earlier stuck-then-2100rpm event). `analyze_logs.py`: only
expected/benign findings. Result:
```
             P=-0.03      P=+0.00      P=+0.03
I=+0.03    2,696,250    1,676,250    1,444,375  <- best
I=+0.00    2,279,375    1,580,000    1,463,125
I=-0.03    2,937,500    1,983,125    1,507,500
```
**Cleanly monotonic in all three `I` rows**, same pattern as the
2026-08-20 ±0.02 transformer sweep — reproduces the "more `P` than
default is better" direction on battery power too, this time without
any contamination.

**Quantified comparison against the third sweep (both ±0.03, same
day):** with the contaminated `P+0.03, I=0.00` point included, the two
matrices look uncorrelated (Pearson r=-0.25, Spearman ρ=0.28 — one
point's ~4.4x distortion swamps everything else). **Excluding just that
one point (8 of 9), the two runs agree noticeably better: Pearson
r=0.71, Spearman ρ=0.69** — clearly stronger than the two ±0.01
transformer runs' repeatability check above (r=0.15, ρ=0.17). Confirms
two things at once: the stiction event really was a one-off
contaminating just that single measurement, not a reproducible
property of `P+0.03, I=0.00`; and at ±0.03 on battery, point-to-point
reproducibility is meaningfully better than at ±0.01 — consistent with
the earlier ±0.01-vs-±0.02 transformer finding that a larger delta step
separates the real P/I effect from measurement noise more clearly.

## 2026-08-24

**First test with everything on battery — motor *and* Raspberry Pi,
not just the motor (the Pi normally runs off the buck converter from
the battery anyway, so this is the intended final setup, closer to it
than the 2026-08-22 tests above).** `run_grid.py`, same ±0.03 deltas as
the two sweeps above (`runs/2026-08-24_170009_grid/`), specifically to
compare against them. All 9 points started normally — no stiction
event this time either. Result:
```
             P=-0.03      P=+0.00      P=+0.03
I=+0.03    2,065,625    1,529,375    1,758,750  <- best
I=+0.00    2,207,500    1,891,250    1,820,000
I=-0.03    2,231,875    2,102,500    1,626,250
```
Monotonic `P` trend holds in 2 of 3 `I` rows (`I=0.00` and `I=-0.03`);
the `I=+0.03` row dips at `P=0.00` then rises slightly at `P=+0.03`,
so not quite as clean as the 2026-08-22 12:28 sweep, but the general
"P above default tends to help" direction still shows.

**Comparison against both 2026-08-22 ±0.03 sweeps:**
- vs. the contaminated 12:12 sweep, with its outlier point included:
  Pearson r=-0.05, Spearman ρ=0.57 (rank agreement holds up better than
  the linear correlation, since the outlier's *magnitude* distorts
  Pearson far more than a rank-based measure). Excluding that one
  point: **Pearson r=0.77, Spearman ρ=0.74.**
- vs. the clean 12:28 repeat: **Pearson r=0.79, Spearman ρ=0.73**, and
  the mean ISE level is nearly identical between the two (ratio 0.98).

Both comparisons land in the same range as the two 2026-08-22 sweeps'
own mutual agreement (r=0.71) — the switch to fully-battery power
(adding the Pi itself, not just the motor) doesn't show any obvious
extra degradation in reproducibility or overall ISE level.

**`P delta=+0.03, I delta=+0.03` specifically, across all three ±0.03
runs so far** (the user's chosen point to track repeatability on):
```
2026-08-22 12:12: 2,045,000
2026-08-22 12:28: 1,444,375
2026-08-24 today: 1,758,750
```
Mean ≈1,749,000, spread roughly ±17% around it — meaningful run-to-run
variation, but within the same ballpark each time, consistent with the
general ±0.03 reproducibility level found above (not the ±0.01-level
noise floor). Not yet enough repeats to call this a real distribution,
just three points.

**One log-analysis artifact worth noting for future reference, not a
real problem:** `analyze_logs.py` flagged a new finding type on this
run — a **poll-loop cadence gap** of `15350480ms` (~4h17m) before a
`[poll]` call at 16:57:18, following the last prior `[poll]` entry at
12:41:27. There is only one `=== watchdog.py — LIVE bus ===` startup
banner in the whole log (no restart), so the watchdog process itself
ran continuously the whole time — the gap is almost certainly a
**system clock jump** (e.g. an NTP correction after the Pi was
reconnected to the network following the battery rewiring earlier that
day), not an actual multi-hour pause in the poll thread. No corrective
action needed; flagged here so a future `analyze_logs.py` run showing
the same "huge idle gap right after a power/network change" pattern
isn't mistaken for a real hang.

**Second full-battery ±0.03 sweep, same day, repeated back-to-back
(`runs/2026-08-24_172518_grid/`) — cleanest result yet, perfect rank
agreement against the 2026-08-22 12:28 sweep.** No stiction event.
`analyze_logs.py`: only expected/benign findings, plus one negligible
latency outlier (`rpm` at 53ms, just over the 50ms threshold) and a
much smaller, mundane poll-loop gap (41,112ms ≈ 41s — ordinary idle
time between sweeps, not a clock-jump artifact like the one above).
Result:
```
             P=-0.03      P=+0.00      P=+0.03
I=+0.03    2,277,500    2,156,250    1,466,875  <- best
I=+0.00    2,173,750    2,091,250    1,795,000
I=-0.03    2,373,125    2,165,625    1,938,750
```
**Cleanly monotonic in all three `I` rows**, best point `P+0.03,
I+0.03` — same combination as the 2026-08-22 12:28 sweep's best point.
**Comparison against prior ±0.03 sweeps:** vs. the 12:28 sweep,
**Spearman ρ=1.000** (perfect rank agreement across all 9 points;
Pearson r=0.77 — magnitudes differ somewhat but the ranking is
identical); vs. this same day's first full-battery sweep (17:00),
r=0.54, ρ=0.73; vs. the 12:12 sweep excluding its contaminated point,
ρ=0.69. The best correlation of any pair measured so far.

`P delta=+0.03, I delta=+0.03` across all four ±0.03 sweeps to date:
```
2026-08-22 12:12: 2,045,000
2026-08-22 12:28: 1,444,375
2026-08-24 17:00: 1,758,750
2026-08-24 17:25: 1,466,875
```
Mean 1,678,750, stdev 245,133 (~15% relative) — a moderate but bounded
spread, consistent with the general ±0.03 reproducibility level, not
the much noisier ±0.01 level.

**Discussion, same day: is it worth permanently changing `KPDEFAULT`/
`KIDEFAULT` in firmware to `P+0.03, I+0.03` yet?** Concluded no, for
two reasons: the measured improvement over the (0,0) center point
varies between ~7% and ~30% across the four ±0.03 sweeps above — a
range comparable to the run-to-run noise itself, not yet a tightly
pinned-down number; and the grid search hasn't found where the P trend
actually levels off or reverses yet (see the ±0.05 sweep immediately
below), so `P+0.03` isn't confirmed to be near the true optimum, just
better than the tested alternatives so far. Decided to keep exploring
via the `pi` delta mechanism (which exists specifically so firmware
defaults don't need to move during exploration) rather than bake
anything into `main.c` yet — revisit once the gradient search converges
on a stable optimum.

**Third sweep, same day, deltas pushed to ±0.05 (P) / ±0.03 (I) —
`p_delta=0.05` chosen specifically to see whether the P trend keeps
improving past +0.03 or starts to level off (`runs/
2026-08-24_173445_grid/`).** No stiction event across any of the 9
points. `analyze_logs.py`: only expected/benign findings (the same
41s/clock-jump-explained gaps already noted above, nothing new).
Result:
```
             P=-0.05      P=+0.00      P=+0.05
I=+0.03    2,838,125    2,141,875    1,306,250  <- best of ALL sweeps so far
I=+0.00    2,621,250    2,060,000    1,459,375
I=-0.03    2,371,250    1,642,500    1,490,625
```
**Still cleanly monotonic in all three `I` rows — the P trend has not
leveled off yet even at ±0.05, and `P+0.05, I+0.03` is the best single
point measured across every sweep to date** (lower than any of the
four ±0.03 sweeps' results, which ranged 1,444,375-2,045,000). The
center point `(0,0)` = 2,060,000 stays consistent with the other four
sweeps' center-point readings (range 1.58M-2.23M) — no baseline drift.

**P/I coupling reconfirmed, more clearly than before:** the size of the
improvement from `P=0.00` to `P=+0.05` differs sharply by `I` row —
-39% at `I=+0.03` (2,141,875 → 1,306,250), -29% at `I=0.00`
(2,060,000 → 1,459,375), only -9% at `I=-0.03` (1,642,500 → 1,490,625).
Raising `P` helps far more when `I` is also raised — consistent with
the P/I coupling first suspected back in the very first ±0.01 sweep
(2026-08-20 above), now showing up clearly at this larger delta scale.

**Next step, not yet done:** push `P` even further (e.g. `p_delta=0.08`)
to find where the trend actually levels off or reverses, since ±0.05
still shows no sign of it — needed before treating any point as a good
gradient-search seed.

**Fourth sweep, same day, deltas pushed to ±0.08 (P) / ±0.03 (I) —
first sweep where the P trend actually turns over, though only in one
of the three `I` rows (`runs/2026-08-24_174226_grid/`).** No stiction
event across any of the 9 points — the `P=-0.08` points show visibly
more overshoot than usual (e.g. `P-0.08, I-0.03` peaks at rpm=1350),
plausibly because a weaker `P` lets the `I` term dominate relatively
more, not an anomaly. `analyze_logs.py`: only the same familiar
expected findings. Result:
```
             P=-0.08      P=+0.00      P=+0.08
I=+0.03    2,810,000    1,585,625    1,615,000   <- turns over here
I=+0.00    3,113,125    2,252,500    1,375,625   <- best this sweep
I=-0.03    3,478,750    2,142,500    1,586,250
```
**The `I=+0.03` row is no longer monotonic: ISE rises slightly from
`P=0.00` (1,585,625) to `P=+0.08` (1,615,000), +1.9%** — the first
reversal seen in five sweeps of consistently falling `P` trends. More
telling: `P+0.08, I+0.03` (1,615,000) is clearly worse than the
previous sweep's `P+0.05, I+0.03` (1,306,250, still the best point
across every sweep to date) — not just noise-sized, a real ~24% jump
back up, pointing at a genuine local optimum somewhere between
`P=+0.05` and `P=+0.08` for that `I` value. **The `I=0.00` and
`I=-0.03` rows are still monotonically improving at `P=+0.08`** — no
turning point found yet for those.

**State of the P/I picture after five sweeps:** the best point overall
remains `P+0.05, I+0.03` (ISE 1,306,250, from the third sweep above).
The region worth a gradient search looks like it's converging on
`P` somewhere around +0.05 to +0.08 combined with `I` around +0.03,
but the `I=0.00`/`I=-0.03` rows haven't been pushed far enough yet to
know if they'd eventually beat that region at a larger `P`. **Next
step, not yet done:** either push `P` further specifically along the
`I=0.00`/`I=-0.03` rows to see if they also turn over, or treat
`P≈+0.05..+0.08, I≈+0.03` as a good-enough seed region and move to the
gradient search.

## 2026-08-25

**Repeat of the ±0.08 sweep — the apparent P-trend reversal from
2026-08-24 did NOT reproduce.** `runs/2026-08-25_123904_grid/`: no
stiction event. Result:
```
             P=-0.08      P=+0.00      P=+0.08
I=+0.03    2,831,875    2,132,500    1,593,125
I=+0.00    3,044,375    2,151,250    1,385,625
I=-0.03    3,025,000    1,985,000    1,359,375
```
**All three `I` rows now monotonic**, including `I=+0.03` — the row
that appeared to turn over on 2026-08-24 (`P=0.00`→`P=+0.08`:
1,585,625→1,615,000, a slight rise) now falls cleanly
(2,132,500→1,593,125). Root cause of the earlier apparent reversal
found by direct comparison: the `P=0.00, I=+0.03` point itself read
1,585,625 on 2026-08-24 vs. 2,132,500 today, a +34.5% swing — one point
drifting, not a real turning point. **Lesson reconfirmed: a single
sweep's apparent trend change needs a repeat before it's trusted**,
same as the earlier stiction-event and best-point findings.

**First ±0.10 sweep (`runs/2026-08-25_124502_grid/`) — still no
turnover, best point now nearly ties the all-time champion.** No
stiction event; `P=-0.10` points show visibly more overshoot again
(same pattern as `P=-0.08`, weaker `P` lets `I` dominate more). Result:
```
             P=-0.10      P=+0.00      P=+0.10
I=+0.03    3,235,000    2,021,250    1,454,375
I=+0.00    3,403,125    1,996,875    1,315,000  <- best this sweep
I=-0.03    3,167,500    1,942,500    1,402,500
```
All three rows monotonic. Best point `P+0.10, I=0.00` (1,315,000) is
within 0.7% of the all-time champion `P+0.05, I+0.03` (1,306,250,
2026-08-24) — effectively tied given the measurement noise already
characterized. The best point shifting from `I=+0.03` (at `P=0.05`) to
`I=0.00` (at `P=0.10`) hints at a broad, fairly flat "valley" region in
the P/I landscape rather than one sharp peak.

**Discussion: is it worth pushing `P` even further (e.g. `p_delta
=0.13`) to keep hunting for a confirmed turnover?** Decided no — the
user's practical judgment: `P delta≈0.10` (`KP≈0.25`, vs. `KPDEFAULT
=0.15`) is already close to a boundary they'd actually consider using;
chasing a mathematical turning point further out than that serves no
real purpose if it's territory that would never be deployed. Redirected
the second planned test run of the day accordingly: instead of pushing
`P` further, repeat `p_delta=0.10, i_delta=0.03` again (reproducibility
check for ±0.10, only one data point existed) — done below.

**Real-time finding, same day: audible/visible "hunting" during the
rise phase, not captured by ISE.** While reviewing `P+0.10, I+0.03`'s
step-response chart, the user noticed the `rpm` trace visibly
oscillating up and down during the first second (`0→575→800→650→950
→750→950`, swings of up to ±300 between 200ms samples) — described as
audible "Rappeln" during the real motor run. ISE alone doesn't capture
this: it only scores distance-from-target, not how roughly the trace
gets there, so two points can have similar ISE while one rises smoothly
and the other hunts back and forth.

**Total Variation tried first, replaced same day by MSSD — see below.**
Discussed control-theory options (Total Variation, decay ratio, damping
ratio); picked **Total Variation** (`TV = Σ|rpm[i+1]-rpm[i]|`) first for
its simplicity against real, noisy, 25rpm-quantized, 200ms-sampled
data — no peak detection needed, unlike decay ratio/damping ratio.
Verified directly against `runs/2026-08-25_124502_grid/`'s three
`P+0.10` point CSVs before the next live run: `I+0.03` (the point that
prompted this) showed the highest `TV_2s` (1900) of the three, `I=0.00`
middle (1225), `I=-0.03` lowest (1075) — matched the by-ear/by-eye
impression at the time. This linear version turned out inadequate (see
the visual-inspection finding below) and was replaced by MSSD the same
day — **the table below and everywhere else in this file uses the
corrected MSSD values throughout, the linear TV numbers were not kept**
(per the user's explicit request to not leave stale TV values lying
around once TV was shown to be the wrong metric).

**Second ±0.10 sweep, same day (`runs/2026-08-25_130502_grid/`) — first
live end-to-end run of the new metric.** ISE reproducibility against
the first ±0.10 sweep was the best measured to date for any delta:
**Pearson r=0.977, Spearman ρ=0.850**. Full point-by-point MSSD table,
both ±0.10 sweeps, recomputed with the final MSSD formula (not the
linear TV originally used live that day):
```
                    ---- Run 1 (124502) ----   ---- Run 2 (130502) ----
point                  ISE  MSSD_2s MSSD_full      ISE  MSSD_2s MSSD_full
(-0.10,-0.03)      3,167,500  84,792   22,739   3,754,375 107,153  28,603
(-0.10, 0.00)      3,403,125  94,722   25,423   3,634,375 123,958  33,125
(-0.10, 0.03)      3,235,000 120,000   32,132   3,115,000 125,764  33,585
( 0.00,-0.03)      1,942,500  67,222   18,382   1,993,125  86,875  23,989
( 0.00, 0.00)      1,996,875  47,222   12,923   2,215,625  59,653  16,783
( 0.00, 0.03)      2,021,250  81,736   21,985   1,960,625  69,583  18,621
( 0.10,-0.03)      1,402,500  57,569   16,305   1,531,875  52,222  14,706
( 0.10, 0.00)      1,315,000  75,486   21,691   1,347,500 113,403  31,360
( 0.10, 0.03)      1,454,375  66,111   19,154   1,325,000  69,583  20,441
```

**Visual inspection caught a real weakness in the original linear-sum
Total Variation metric.** Four charts requested and produced from run 2
(`P=0.00/I=0.00` center, plus all three `P=+0.10` points). By eye,
`P+0.10, I=0.00` looked clearly rougher than `P+0.10, I=-0.03` — but
their linear `TV_2s` values (1825 vs. 1600 at the time) were only ~14%
apart, too close to explain "stark" vs. "leicht" (strong vs. light) as
perceived. Root cause found by inspecting the raw samples: `I=0.00`'s
first second has one sharp double-reversal (`0→900→575→850`, a 325-rpm
single regression) that a plain absolute-difference sum weights the
same as many small, evenly-spread wobbles — `I=-0.03`'s trace has a
similar total linear TV but no single jump anywhere near that large.

**Fix: switched to Mean Square Successive Difference (MSSD, von
Neumann 1941) — squared successive differences, matching ISE's own
quadratic-penalty philosophy.** Recomputing the same two traces
squared (run 2): `I=0.00` MSSD_2s=113,403 vs. `I=-0.03`=52,222 —
roughly **2.2x apart**, clearly separating them in a way that matches
the actual visual/audible difference, unlike the ~14%-apart linear
version. `run_grid.py` renamed throughout: `_compute_tv()` →
`_compute_mssd()`, `TV_SHORT_WINDOW_S` → `MSSD_SHORT_WINDOW_S`, CSV
columns `tv_2s`/`tv_full` → `mssd_2s`/`mssd_full`, console labels
updated. Verified the new function reproduces the hand-computed values
exactly. See root `CLAUDE.md`'s Grid Search section for the permanent
design writeup of MSSD.

**Correction, same day: the "hunting event didn't reproduce" claim
below was wrong — it was based on comparing the two runs' linear TV
values, the metric already shown to be inadequate.** Recomputing both
runs with MSSD (table above) instead: `P+0.10, I+0.03` — the point that
originally prompted this whole investigation — reads MSSD_2s=66,111
(run 1) vs. 69,583 (run 2), only **~5% apart**. Far from "didn't
reproduce," this is one of the *more* consistent points measured. The
relative ranking within `P=+0.10` also held across both runs:
`I=-0.03` calmest, `I=+0.03` mid, `I=0.00` roughest — same order both
times. **The one point that genuinely doesn't reproduce well is
`I=0.00` itself**: 75,486 (run 1) vs. 113,403 (run 2), a real +50%
swing — that one still needs another look before trusting its exact
magnitude, but the overall ranking pattern is solid. Net effect: MSSD
earned more trust than the (wrong) same-day "didn't reproduce"
conclusion suggested — the original by-ear/by-eye "Rappeln" at
`P+0.10, I+0.03` was real and repeatable, not noise.

**State after today.** (1) The P trend still hasn't found a real
turnover within deltas the user would actually consider deploying
(~±0.10) — `P≈0.05..0.10, I≈0.00..0.03` looks like a broad, fairly flat
good region rather than one sharp optimum. (2) MSSD's ranking behavior
looks trustworthy after the correction above, though absolute
magnitudes (like `I=0.00`'s) can still swing a fair amount between
runs — same general caution as ISE at small deltas, just not as severe
as first thought. Natural next step: start the gradient search, using
ISE as the primary driver (well-validated) and MSSD as a secondary
signal/tie-breaker between similarly-scoring candidates, gathering more
MSSD data points naturally as the search proceeds rather than running a
dedicated characterization sweep first.

**First two real `run_grid_row.py` rows, same day, right after the tool
was built — both clean, no stiction, and a real complication to the
`P`-vs-roughness story found in the second one.**

Row 1, `P` fixed at `+0.03`, `I` from -0.08 to +0.08 in 0.02 steps
(`runs/2026-08-25_143636_row/`):
```
I=-0.08: ISE=1,781,875  MSSD_2s=28,611  MSSD_full= 8,419
I=-0.06: ISE=1,535,625  MSSD_2s=41,736  MSSD_full=11,967
I=-0.04: ISE=1,510,000  MSSD_2s=34,583  MSSD_full= 9,669
I=-0.02: ISE=1,555,000  MSSD_2s=37,917  MSSD_full=10,551
I=+0.00: ISE=1,733,125  MSSD_2s=52,431  MSSD_full=14,265
I=+0.02: ISE=1,820,000  MSSD_2s=54,514  MSSD_full=14,853
I=+0.04: ISE=1,384,375  MSSD_2s=45,764  MSSD_full=12,702
I=+0.06: ISE=1,370,000  MSSD_2s=51,042  MSSD_full=14,412
I=+0.08: ISE=1,686,875  MSSD_2s=58,819  MSSD_full=16,213
```
ISE has two local dips (`I≈-0.04` and `I≈+0.06`), not a single clean
minimum — treated as provisional, not yet repeated. MSSD shows a fairly
clear rising trend with `I`: calmest at `I=-0.08`, roughest at `I=+0.08`
— matches the "I costs smoothness" side of the Candidate Selection
Philosophy directly, at this specific `P`.

Row 2, `P` fixed at `+0.08`, same `I` grid (`runs/2026-08-25_144213_row/`):
```
I=-0.08: ISE=1,496,875  MSSD_2s=61,458  MSSD_full=17,408
I=-0.06: ISE=1,507,500  MSSD_2s=61,667  MSSD_full=16,875
I=-0.04: ISE=1,381,875  MSSD_2s=80,625  MSSD_full=22,206
I=-0.02: ISE=1,331,250  MSSD_2s=62,500  MSSD_full=17,518
I=+0.00: ISE=1,515,000  MSSD_2s=82,014  MSSD_full=22,298
I=+0.02: ISE=1,465,625  MSSD_2s=52,500  MSSD_full=15,607
I=+0.04: ISE=1,508,750  MSSD_2s=55,764  MSSD_full=16,985
I=+0.06: ISE=1,230,000  MSSD_2s=89,722  MSSD_full=24,301  <- best ISE of any row/grid so far
I=+0.08: ISE=1,412,500  MSSD_2s=60,208  MSSD_full=17,518
```

**Comparing the two rows point-for-point (same 9 `I` values, only `P`
differs): ISE mostly favors `P=0.08` (better at 7 of 9 `I` values,
consistent with every earlier finding that more `P` helps ISE), but
MSSD is higher at `P=0.08` than at `P=0.03` at almost every single `I`
value** — the opposite of what the 2nd-order damping-ratio model
predicted. That model's supporting evidence so far only ever compared
*negative* `P` against `0` and positive `P` (`-0.10→0.00→+0.10`, see
above) — this is the first comparison entirely *within* the positive-`P`
range, and it suggests roughness might not simply keep falling forever
as `P` rises: there could be a genuine trough (a `P` range that's
calmest) rather than "more is unconditionally better," or other effects
(loop gain amplifying quantization/sampling noise, etc.) start to
dominate once `P` is already well above zero. **Not resolved — flagged
here for the fuller row-based matrix below to actually settle.** Also
notable: the best-ISE point of the whole project so far (`P+0.08,
I+0.06`, ISE=1,230,000) is simultaneously the *roughest* point in its
own row (MSSD_2s=89,722) — a concrete, real example of the ISE-vs-
smoothness tension the Candidate Selection Philosophy exists to manage,
not just a theoretical concern.

## Planned Row-Based Matrix (started 2026-08-25, not yet complete)

Full systematic sweep via `run_grid_row.py`, one row at a time, same
`I` grid throughout (`-0.08` to `+0.08` in `0.02` steps) so every row
lines up cleanly for `analysis/grid_heatmap.py` later. `P` covers its
whole safety-capped range (`±0.10`) in `0.02` steps — 11 rows in total.
Check off each row here as it's actually run; copy the command
directly, `fixed_value` is the `P` delta for that row:

- [x] `python3 run_grid_row.py i -0.10 0.02`
- [x] `python3 run_grid_row.py i -0.08 0.02`
- [x] `python3 run_grid_row.py i -0.06 0.02`
- [x] `python3 run_grid_row.py i -0.04 0.02`
- [x] `python3 run_grid_row.py i -0.02 0.02`
- [x] `python3 run_grid_row.py i  0.00 0.02`
- [x] `python3 run_grid_row.py i  0.02 0.02`
- [x] `python3 run_grid_row.py i  0.03 0.02` — **done**, `runs/2026-08-25_143636_row/` (off-grid value, kept as-is rather than re-run at 0.02/0.04, see results above)
- [x] `python3 run_grid_row.py i  0.04 0.02`
- [x] `python3 run_grid_row.py i  0.06 0.02`
- [x] `python3 run_grid_row.py i  0.08 0.02` — **done**, `runs/2026-08-25_144213_row/`, see results above
- [x] `python3 run_grid_row.py i  0.10 0.02`

Once several more rows exist, run
`python3 analysis/grid_heatmap.py runs/<row1> runs/<row2> ...` (list
every row directory) to merge them into the three heatmaps.

## Row-Based Matrix Completed, Heatmaps Generated (2026-08-25)

All 11 planned rows above were run the same day, plus the two earlier
bonus rows (`+0.03`, off-grid). Two rows needed a repeat after the
built-in stiction check (`run_grid.py`'s `_report_stiction_warnings()`,
built earlier the same day) flagged a point:
- `P=+0.02`: first attempt (`runs/2026-08-25_151038_row/`) flagged
  `I=-0.02` (stuck 0.61s); repeat (`runs/2026-08-25_152338_row/`) used
  for the heatmap below.
- `P=-0.04`: first attempt (`runs/2026-08-25_154502_row/`) flagged
  `I=-0.08` (stuck 1.21s); repeat (`runs/2026-08-25_154938_row/`) used.
- `P=-0.10`: **three separate attempts, every single one flagged at
  least one point** (`runs/2026-08-25_161224_row/`, `_161522_row/`,
  `_161855_row/`) — no clean repeat was ever achieved. All three kept
  and merged together (see below) rather than picking one, since the
  checker's own tool (`analysis/grid_heatmap.py`) already averages
  repeated coordinates and reports `n=`.

**Deeper look at the raw start-up timing across every row (not just
the checker's binary flag) reveals something more specific than "rare
random stiction," and reframes the whole `P=-0.10` situation.**
Checking every point's first non-zero `rpm` sample across all 16 row
directories: the two officially-flagged repeats above are real outliers
(0.61s, 1.21s), but a much larger set of points across the *negative*-`P`
rows sit right at **0.60-0.61s** — just at or barely past the checker's
threshold — including nearly *every single point* in all three `P=-0.10`
attempts (605, 606, 605, 606, 606, 606, 606, 605, 605 ms in one attempt
alone), and several points each in `P=-0.06` and `P=-0.08` too. This is
a different picture from "one rare unlucky point per sweep": at
`P=-0.10`, a slow (~0.6s) start looks close to the *norm*, not a rare
one-off — consistent with simple control theory (a much lower `P` gain
than default gives less initial torque, so it plausibly just takes
longer to overcome static friction every time, not only occasionally).

**Important methodological caveat this exposes: `capture_step_response.py`
samples `rpm` every 200ms, so "first non-zero sample" has only ~200ms
resolution.** A real start anywhere between the 400ms and 600ms samples
reads identically as "600ms" regardless of whether the true start was at
410ms or 590ms — the tight clustering right at 604-606ms across so many
points is at least partly a quantization artifact of the sampling grid,
not proof every one of those points shares an identical underlying
delay. This also explains why the user's own by-eye review during
testing called several of these "borderline" rather than clearly one
way or the other (see below) — the 0.6s threshold sits almost exactly
on a sampling-grid line, so small real timing differences land on
either side of it somewhat arbitrarily. **`STICTION_STUCK_THRESHOLD_S`
being a simple fixed cutoff at this sampling resolution can't cleanly
separate "genuinely locked at a bad rotor position" from "just a bit
slow to start because `P` is low" — a real, finer-grained answer needs
Saleae's 10MHz Hall-edge resolution, not more LIN polling.**

**One recurring coordinate worth flagging on its own, separate from the
general negative-`P` slow-start pattern: `P=+0.02, I=-0.02` was slow to
start in *both* of its two attempts** — 0.81s (first, flagged) and 0.61s
(repeat, borderline) — at the *same* (P, I) pair both times, not two
different random points. Positive `P` here, so the "low-`P`-means-
slower" explanation doesn't obviously apply — this specific coordinate
may deserve a dedicated repeat check later, separate from the general
negative-`P` pattern above, before concluding it's just coincidence.

**`P=-0.10` is a good candidate for a future Saleae investigation of the
stiction/slow-start mechanism, per the user's own suggestion** — of
everything tested, it's the only delta where slow starts were observed
on essentially every attempt, not an occasional fluke, making it the
most *reproducible* place to point a Saleae capture at the Hall
channels and actually see what's happening during the stuck period
(testing the Hall-sector-boundary hypothesis discussed earlier, or
distinguishing it from a simple weak-torque slow start). Not scheduled
yet, no strategy decided — flagged here as a good target when that
investigation happens.

**Heatmaps generated** (`analysis/grid_heatmap.py`, output in
`runs/2026-08-25_162629_heatmap/`) from the 11 rows above (14 input
directories counting the three `P=-0.10` attempts merged together): 108
unique (P, I) coordinates, 126 individual point measurements total.

ISE heatmap: the P-trend is now visible across the *whole* plane, not
just a few sweeps — clearly lower (better) on the right (`P` positive)
than the left (`P` negative). **New all-time best point: `P+0.04,
I+0.08`, ISE=1,226,875** — beats the previous champion (`P+0.05,
I+0.03`, 1,306,250, 2026-08-24). The `P=-0.10, I=+0.04` cell reads
6,545,625, clearly the single worst cell on the whole map — inflated by
averaging in the one attempt's flagged stiction point at that exact
coordinate with the other two (cleaner) attempts; treat this one cell
with extra caution, the averaging dilutes but doesn't fully remove the
contamination.

MSSD heatmaps: same broad "P` positive tends calmer" pattern as before,
but with a new, different single-point anomaly found while reviewing
it — `P=+0.06, I=0.00` reads MSSD_2s=325,417 and MSSD_full=87,224, both
far above every neighboring cell (typical neighbors are 30,000-150,000
and 10,000-40,000 respectively). Traced to the raw CSV
(`runs/2026-08-25_150103_row/point_p+0.06_i+0.00.csv`): `rpm` went
`0 → 0 → 25 → 1550 → 800` across four consecutive 200ms samples — a
sharp, single-sample spike to 55% over target, then back down, with no
preceding extended stall (only 405ms at low values, under the stiction
threshold, so `_detect_stiction()` correctly didn't flag it — it isn't
built to catch this pattern). This is a different anomaly shape than
both the original stiction event (long stall then overshoot) and the
general negative-`P` slow start above — a brief, isolated overshoot
spike with no stall precursor at all. Only measured once (`n=1`); the
`P=+0.06` MSSD value should be treated as unconfirmed until repeated.

