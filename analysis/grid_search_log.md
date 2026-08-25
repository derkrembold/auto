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
