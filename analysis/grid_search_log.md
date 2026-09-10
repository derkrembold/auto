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

**Terminology added 2026-08-26, and a second, compounding mechanical
cause raised alongside the electromagnetic one above.** The
"Hall-sector boundary rest position" idea above has an established
name in BLDC motor control: a **Dead Zone** — a rotor position (usually
near a commutation sector boundary) where the currently active phase
configuration produces little to no torque. Matches this project's
hypothesis directly, not just an analogy.

**Mechanical static friction ("stiction") is a separate, second
possible contributor, and the two can compound rather than compete as
explanations.** A Dead Zone position only means the *available* torque
is weak at that instant — whether that's enough to actually stall the
rotor also depends on how much torque is needed to break static
friction and start moving at all. A rotor resting at a *mild* Dead Zone
might still start fine most of the time if breakaway friction is low
that moment (bearing lubrication state, exact contact point, etc. —
inherently a bit variable run to run); resting at that *same* mild Dead
Zone on a run where friction happens to be a bit higher could be enough
to actually stall it. This gives a natural explanation for why the
stall duration and its exact trigger point aren't perfectly
repeatable/predictable even at the same nominal `P`/`I` and even at the
same rough rotor region (see the `P=-0.10` row's per-point timing
spread, ~0.60-0.61s across most points but 1.4-1.5s for a couple —
consistent with "usually a mild Dead Zone, occasionally compounded by
higher-than-usual friction that same run," not one fixed mechanism with
one fixed severity).

**Two named candidate fix strategies discussed, both deliberately not
designed or built yet — mechanism verification (the planned Saleae
investigation) comes first:**
- **Lead Angle Control (a.k.a. Phase Advance):** commutate to the next
  state slightly *before* the Hall sensor's nominal transition, rather
  than exactly at it. Classically discussed in BLDC literature more as
  a running-speed efficiency technique (compensating winding-inductance
  current lag as electrical frequency rises) than a standstill fix, but
  the same underlying principle — never dwelling exactly at a
  sector-edge Dead Zone — directly supports it as a candidate here too,
  and it's conceptually close to the project's own earlier "kick to the
  next-next commutation state during a stall" idea, just continuous
  rather than an occasional forced jump.
- **Forced/Open-Loop Commutation start-up:** a more standstill-specific
  standard technique — briefly drive a fixed blind commutation sequence
  regardless of Hall feedback to get the rotor moving, then hand off to
  normal closed-loop Hall commutation once enough speed is reached.
  **User confirmed the precise relationship: the project's own
  kick-start idea is the goal/strategy ("still absolutely current"),
  and Forced/Open-Loop Commutation is the established mechanism that
  realizes it** — periodically forcing the next-next commutation state
  during a stall, rather than waiting on real Hall feedback, is a
  kick-start implemented via forced/open-loop commutation, not two
  competing names for the same thing at the same level.

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

## 2026-08-26: Saleae Investigation Session, Detector Gap Found, Kick-Start Design Started

**Plan executed: repeat a `P=-0.10` row coordinate with `run_experiment.py`
(Saleae running) until a genuine stiction event is caught.** `P=-0.10,
I=+0.04` chosen first (had the single worst delay, ~1.2-1.4s, in
yesterday's row data). Confirmed `run_experiment.py` itself has no
`P_DELTA_MAX_DEFAULT`-style cap of its own (only `run_grid_row.py`
does) — user explicitly declined going to `P delta=-0.11` anyway,
correctly noting it would break yesterday's own deliberately-set
boundary for no real benefit (the Dead Zone mechanism is about rotor
rest position, not the exact `P` value).

**Five real attempts, `P=-0.10` throughout, `I` varied (`+0.04` ×2,
then `-0.06`/`-0.08`-ish ×3 based on the user's own reasoning that a
weaker `I` should delay the integral term's ability to break through a
Dead Zone, making a bigger event more likely to be caught):**
- Attempts 1-4: clean logs, Saleae trigger caught every time, Hall
  ground truth closely tracked LIN `rpm` throughout (confirming the
  overshoots seen are real, not measurement artifacts) — but all four
  showed only *moderate* events: ~200-400ms at/near zero (under the
  0.6s stiction threshold, `_detect_stiction()` correctly returned
  `None` each time), followed by a moderate overshoot (1300, 1350-1375,
  1375, 1325 rpm — 30-38% over the 1000 target).
- **Attempt 5, the real catch (`P delta=-0.1, I delta=-0.06` per the
  plot title):** `rpm` sequence `0, 25, 0, 0, 0, 1550, 1800, ...` across
  six consecutive 200ms samples — briefly ticked to 25 at 204ms, then
  fell *back* to 0 for three more samples (~800ms total near-zero),
  then jumped to 1550 and peaked at **1800rpm (80% over target)** —
  much closer in severity to the original 2026-08-22 event (2100rpm)
  than the four moderate attempts. Saleae Hall ground truth showed
  something LIN alone couldn't: during the "stuck" window, the rotor
  wasn't perfectly motionless — Hall-edge-derived rpm oscillated
  roughly between 50 and 350 (never reading a hard, flat zero the way
  LIN did) before the real breakaway. Plausible reading: the rotor was
  rocking/hunting near a Dead Zone boundary (weak or direction-
  ambiguous torque there) rather than in a hard mechanical lock —
  consistent with the Dead Zone hypothesis, and a genuinely new piece
  of evidence for it, not just circumstantial.

**Real bug found in `_detect_stiction()` (`run_grid.py`) from this
attempt 5 data: it missed this event entirely.** The function only
counts zeros from the very first sample and stops at the *first*
non-zero value — the brief 25rpm blip at 204ms in attempt 5 broke the
count immediately, so it never saw the three zeros that followed. This
is a genuine detector gap, not yet fixed (discussed, not implemented
yet — see below for the direction agreed on).

**Fix direction discussed (not yet built):** redefine "stuck" as "`rpm`
below a low threshold (e.g. ~10% of target) and not yet *sustainably*
risen above it for a few consecutive samples" instead of "literally
zero from sample one." Tolerates a brief blip like the 25rpm one
without ending the stuck-count early, while still correctly recognizing
a genuine, sustained rise (as seen in the four moderate attempts) as
"started." Needs validation against the whole existing corpus (the
original 2026-08-22 event, today's 4 moderate + 1 severe attempts,
yesterday's ~18+ clean row points) before being trusted — not done yet,
explicitly deferred pending further discussion.

**Kick-start firmware design discussion started (not built, no
timeline yet) — this is the mitigation strategy referenced since
2026-08-25, now being designed for real.** Confirmed spelling:
**stiction** (static + friction), not "striction."

- **Detection should live in `main.c`, not the watchdog.** These are
  two unrelated mechanisms: the watchdog's `_check_stall()`
  (`raspi/watchdog/watchdog.py`) is a real-time *safety* cutoff running
  on the Pi (3.0s grace period, stops the motor on true stall) —
  completely separate in purpose, threshold, and trigger condition from
  a firmware-side kick-start, which would need to react much faster and
  push the motor forward rather than cut it. Confirmed this connects
  directly to `STM32/CLAUDE.md`'s existing (deprioritized) "Stall
  Detection" plan — the *detection* half (no Hall transition despite a
  nonzero command) is the same building block already sketched there,
  just paired with a kick-start *reaction* instead of only a cutoff.
- **Detection timing analysis, real data:** checked "time to first
  non-zero `rpm`" across all 268 available point CSVs (every grid, row,
  and experiment run so far). Distribution (all values land on the
  200ms LIN sampling grid, a real resolution limit, not a true
  continuous distribution): 50.4% already moving by the very first
  sample (204ms), 29.1% by 404ms, 17.2% by 605ms — **96.7% cumulative
  by 605ms** — only 3.3% (9 of 268) took longer (805ms-1406ms), which
  is the genuine problem tail this whole investigation is about.
  Median 208ms, mean 359ms. Caveat repeated: LIN's 200ms sampling can't
  resolve anything finer than its own grid, so "50.4% at the first
  sample" really means "sometime before 204ms," not literally at 204ms.
- **Firmware threshold decided: 4 consecutive 100ms `rpm`-computation
  windows reading `rpm=0` (i.e. 400ms) before triggering a kick-start.**
  Deliberately reuses the firmware's own existing 100ms `SAMPLERATE`
  `rpm`-calculation cycle as the counting unit (see `STM32/CLAUDE.md`'s
  RPM Measurement Resolution section) rather than a new raw-Hall-edge
  timer — `rpm==0` over a full 100ms window already means zero Hall
  transitions that whole window, a naturally debounced signal, not
  raw, unfiltered GPIO noise. 300ms (3 windows) was the first anchor
  (comfortably below the ~700ms+ problem tail, above the ~605ms
  covering 96.7% of normal starts), then widened to 400ms (4 windows)
  as a deliberate compromise for extra margin against false-triggering
  on a normal-but-slightly-slow start, at the cost of 100ms slower
  reaction to a genuine stall — the LIN data can't distinguish 300ms
  from 400ms precisely enough to prefer one on data alone, so this was
  a judgment call, not a data-forced one.
- **Not yet decided:** the actual kick-start mechanism itself (how far
  to jump ahead — "next-next" state specifically, or something else;
  how long to hold the forced state; how often to retry if the first
  kick doesn't work; how/when to hand back to normal closed-loop Hall
  commutation). Explicitly deferred — this session only settled
  detection timing, not the response.

## 2026-08-27: Kick-Start Implemented in `main.c` (User's Own Code,
Reviewed), Confirmed Firing on Real Hardware

**User implemented `driveKickStart()`/`driveStepKickStart()` themselves
in `STM32/firmware/Core/Src/main.c`** (per their own explicit request
throughout — Claude reviewed/discussed, never edited `main.c` directly),
realizing the 400ms/4-window detection threshold decided above via the
established "Forced/Open-Loop Commutation" mechanism.

**Mechanism, confirmed correct by direct derivation:**
`driveStepKickStart(speed)` mirrors `driveStep()`'s Hall-read-and-drive
structure exactly, but targets one additional real commutation step
ahead of what `driveStep()` itself would drive — `Hall+2` for CW
(`driveStep()`'s own CW increment is `Hall+1`) and `Hall+4` for CCW
(`driveStep()`'s own CCW increment is `Hall+2`, an inherent asymmetry in
the existing, already-tested commutation table, not a new bug). Called
from `driveKickStart()` once `stuckwindowcount` (incremented once per
100ms `SAMPLERATE` window with `rpm==0` and a nonzero commanded speed)
reaches `KICKSTART_STUCK_LOWER_WINDOWS=4`, up through
`KICKSTART_STUCK_UPPER_WINDOWS=8` — an escalating repeat count (1
kick+normal pair at window 4, growing to 5 pairs at window 8),
deliberately minimal/experimental as a starting point, not yet tuned.
`driveKickStart()`'s call site stays in the "lower" block (right after
`rpm` is recomputed and the SAMPLERATE timer stops), a deliberate
trade-off: moving it to the timer-*start* block would avoid a small
(max ~13ms across the largest escalation) drift in the real-time
sampling cadence, but isn't safety-relevant, so left as-is for now.

**`KICKSTART_SPEED` derived from a real current-limit calculation, not
picked arbitrarily** (an earlier draft used `GLOBALRATE/20`, flagged
during review as coincidental/unjustified): average current under PWM
= `Duty × V_batt / R`, valid independent of the motor's unknown winding
inductance specifically because the *average* value of an RL circuit's
current under periodic drive depends only on the average voltage and
resistance (inductance only affects ripple/whether conduction is
continuous) — and at these low duty cycles, conduction is plausibly
discontinuous anyway, which would only make the true average *lower*
than this estimate, i.e. the calculation is a conservative upper bound
either way. Inputs: `R=0.065Ω` (winding resistance U-V/V-W/U-W, motor
datasheet — matches directly, since one active commutation state always
drives exactly two windings in series), `V_batt_max=27V` (full battery,
root `CLAUDE.md`'s Battery section), `I_max=5A` (target). Gives
`Duty_max ≈ 1.20%` → `speed ≈ GLOBALRATE/83`; implemented as
`GLOBALRATE/80` (≈5.19A at 27V, close enough, not re-tightened).

**Three real bugs found in review, all fixed before flashing:**
1. **Missing `;` and missing `i++`** in the escalation `while` loop —
   would have been a genuine infinite loop on real hardware (motor
   stuck fully unresponsive to LIN, including `speed 0`, until physical
   power was cut) had it reached hardware unfixed. Caught by code
   review, not by testing.
2. **Kick direction bug:** `KICKSTART_SPEED` is a fixed positive
   constant: the first implementation passed it unconditionally to both
   `driveStepKickStart()`/`driveStep()`, meaning the kick always drove
   CW regardless of the actually-commanded direction — a CCW stall
   (negative `controlvariable`) would get kicked the *wrong* way. Fixed
   to `speed >= 0 ? KICKSTART_SPEED : -KICKSTART_SPEED`.
3. **Diagnostic-counter byte bug** (see below): `(kickStartCount >> 8) &
   0xFF` always transmitted `0`, since `kickStartCount` is capped `mod
   16` and fits entirely in the low byte. Fixed to `kickStartCount &
   0xFF`.

**`kickStartCount` — explicit throwaway/experimental diagnostic, may or
may not survive in this form.** Built specifically because rpm-trace
timing alone couldn't answer "did the kick-start actually fire" (a
`P=-0.10,I=-0.06` repeat looked identical, timing-wise, to yesterday's
4 *pre-kick-start* "moderate" baseline events — the ~400ms stuck window
in every case lands almost exactly on the 400ms trigger threshold,
making the rpm curve alone ambiguous either way). `st3mot`'s `data[3]`
(previously `checksumErrorCount`'s unused high byte — `checksumErrorCount`
itself is now transmitted as a single byte, `data[2]` only, plenty for a
rare-event counter) repurposed as a free-running `mod 16` counter,
incremented once per 100ms *firing* (not once per stall event — up to 5
increments possible per single stall). `raspi/watchdog/linbus.py`:
`get_motor_counters()` updated to match (checksum now `data[2]` only);
new, separate `get_kick_start_count(lin)` reads `data[3]` — kept
separate specifically so `watchdog.py`'s `selftest()` (6 existing call
sites) needed zero changes. New `watchdog.py` "kickcount" verb,
`motorcontrol.py` help text updated, `run_experiment.py` now reads
`kickcount` once before the first capture attempt and once after the
last, prints the before/after/delta (with a `mod 16` wraparound
caveat — practically not a concern within one ~7-8s capture). Test
suite extended (2 new tests), 130/130 passing.

**Confirmed no regression from the byte-layout split, via a real
`selftest()` run:** `checksumErrorCount` and `bodyTimeoutCount` reacted
independently and correctly (each +1 only for its own provocation,
`kickStartCount` untouched throughout all three provocations) — no
bit-overlap between the three counters.

**Real-hardware confirmation, 4 `run_experiment.py` runs, kick-start
firing tied directly to known-problematic P/I combinations for the
first time (not just timing inference):**

| run | P delta, I delta | rpm (first ~1s) | kickcount before→after | kicks fired |
|---|---|---|---|---|
| `142957` | -0.10, -0.08 | 0,0,0,150,950 (peak 1200) | 5→7 | 2 |
| `143100` | -0.10, -0.06 | 0,0,0,350,1175 (peak 1275) | 7→8 | 1 |
| `143150` | -0.10, 0.0 | 0,0,0,200,1275 (peak 1425) | 8→9 | 1 |
| `143227` | **0.0, 0.0 (default)** | 0,**50**,**875**,825,825 (peak 975) | 9→9 | **0** |

All three `P=-0.10` runs show the familiar ~400-600ms stuck window
*and* the kick-start firing (1-2x); the default-gains run shows an
almost immediate, clean start (`rpm` already 50 by 204ms, 875 by 404ms)
*and* zero kicks — exactly the expected behavior, firing only when a
real dead-zone/stiction condition is present, silent otherwise.

**Still open / not yet resolved:**
- Whether the kick-start actually **improves** recovery (faster
  breakthrough, lower overshoot) is still not cleanly separated from
  ordinary run-to-run variance — every kick-start-confirmed event so
  far (this session) looks similar in magnitude to yesterday's 4
  *pre-kick-start* "moderate" baseline events (peak ~1200-1425 vs.
  1300-1375 yesterday, both ~30-40% overshoot). A genuinely severe
  (~800ms+ stuck) reproduction under the new firmware, with `kickcount`
  confirming multiple escalated attempts, is needed before claiming the
  mechanism *works*, not just that it *fires*.
  Yesterday's real severe event (Attempt 5, `P=-0.10,I=-0.06`, 800ms
  stuck, 1800rpm overshoot) has not yet been reproduced under the new
  firmware.
- `driveKickStart()`'s call site stays in the timer-*stop* block
  (accepted small taktrate-drift trade-off, see above) — not revisited.
- Escalation repeat-count (currently 1-5 pairs) and `kickStartCount`'s
  per-firing (not per-event) granularity are both unrefined/
  experimental — may change, or the whole diagnostic counter may be
  dropped once the kick-start itself is trusted.
- No fault/escalation behavior once `stuckwindowcount` exceeds
  `KICKSTART_STUCK_UPPER_WINDOWS=8` — the firmware just stops trying
  silently; still relies entirely on the Raspi-side watchdog's own
  `_check_stall()` (3.0s grace period) as the actual safety backstop.

## 2026-08-27 (continued): `P=-0.10` Row Re-Run With Kick-Start Active
— Two Extreme Cases Found, Both Expose Real Gaps

**Motivation:** since the kick-start now fires automatically, a clean
"with vs. without" A/B on the *same* firmware is no longer possible —
the mechanism we want to evaluate is exactly what would prevent a
severe event from developing in the first place. Chosen approach:
re-run the *exact same* row already on record from before the
kick-start existed (`python3 run_grid_row.py i -0.10 0.02` — see the
2026-08-25 section above, 3 prior attempts, every one flagged
stiction), and compare the resulting distribution against that
documented pre-kick-start baseline. `run_grid.py`/`run_grid_row.py`
extended the same day to read `kickcount` before/after *every point*
(not just once per whole run like `run_experiment.py`) via the new
`_read_kickcount()` — new `kicks` column in `grid_results.csv`, printed
per-point/matrix same as `ise`/`mssd_*`.

**Results (`runs/2026-08-27_144449_row/grid_results.csv`):**
```
i_delta   ise         mssd_full    kicks
-0.08     3,869,375     22,757       2
-0.06     3,870,625     31,250       2
-0.04     3,342,500     25,313       1
-0.02    16,615,625    133,456       5   <- extreme #1
 0.00     3,394,375     26,140       1
 0.02     3,477,500     30,110       1
 0.04     3,342,500     29,596       1
 0.06     2,963,125     33,787       0
 0.08     4,467,500     66,765       0   <- extreme #2
```
7 of 9 points landed in an unremarkable ~2.9-3.9M ISE / ~23-34k
`mssd_full` band, each with 0-2 kicks — consistent with the earlier
`run_experiment.py` confirmations (moderate stalls, kick-start engages
a couple of times, resolves normally). Two points stand well outside
that band, each exposing a different real gap in the current design.

**Extreme #1 — `I delta=-0.02`, ISE 16.6M (~5x neighbors), `mssd_full`
133k (~4-5x neighbors), `kicks=5` (the maximum possible):**
```
rpm: 0 (x9, from 9ms through 1806ms) -> jump to 2725 by ~2012ms
current: -2.29A / -2.34A at the jump (vs. the usual ~-0.5A elsewhere)
```
Chart: `runs/2026-08-27_144449_row/extreme_point_p-0.10_i-0.02.png`.
The motor was stuck for **~1.8-2.0s** — the kick-start correctly fired
through all 5 escalation steps (windows 4 through 8, i.e. it kept
trying up to the 800ms mark), but that wasn't enough. Past window 8
the firmware silently stops attempting anything further (the open gap
already flagged above, "No fault/escalation behavior...") — the motor
then stayed stuck for **another full second** with zero intervention
before finally breaking free on its own, into the most violent
overshoot recorded in this whole project so far (+172.5% over target,
current more than 4x the usual peak). **This is the first real-hardware
case where that documented gap actually mattered**, not just a
theoretical concern: the mechanism engaged correctly, exhausted its
allotted attempts, and the underlying stall outlasted them.

**Extreme #2 — `I delta=+0.08`, ISE 4.47M (~1.2x neighbors), `mssd_full`
66.8k (~2x neighbors), `kicks=0` (never engaged at all):**
```
rpm: 0, 25, 0, 175, 1575, 1625, 1250, 975, 825, 900, 975, ...
```
Chart: `runs/2026-08-27_144449_row/extreme_point_p-0.10_i+0.08.png`.
A brief 25rpm blip at 205ms reset `stuckwindowcount` back to 0 (per
`driveKickStart()`'s `measuredrpm != 0` check — any nonzero sample
counts as "moving," no debounce) before the 4-window threshold could
be reached; by the time it read 0 again, only ~1-2 windows passed
before real motion resumed at 606ms — never enough consecutive stuck
windows for a single kick to fire. Yet the event was still clearly
rough: peak overshoot +62.5%, plus a distinct **second dip** to
~825-900rpm around 1.5-1.7s before finally settling — a rockier
recovery than the untouched, kick-engaged neighbors despite zero
kick-start involvement. **This is the exact same blip-reset failure
mode already found in the Python-side `_detect_stiction()`** (see the
2026-08-26 section above — a brief non-zero blip breaks a naive "still
at zero" count) — now confirmed to exist in the firmware's own
detection logic too, not just the offline analysis tooling. Same fix
direction likely applies: a low-but-nonzero threshold plus a
sustained-rise confirmation instead of "any nonzero sample immediately
means recovered," though not yet designed or built for the firmware
side.

**Net takeaway:** the kick-start mechanism is confirmed working
correctly *when it engages* (fires only on genuine stuck conditions,
silent at default gains, per the 2026-08-27 `run_experiment.py`
confirmations above) — but this row re-run surfaced two distinct,
real ways it can still fail to help on a genuinely severe event: (a)
the escalation cap being reached before the real stall resolves, and
(b) a transient blip preventing it from ever starting to count in the
first place. Both are concrete next design targets, not yet addressed.

**Follow-up the same day: `I=-0.02` repeated 6x via `run_experiment.py`
— the severe event does NOT reproduce.** Discussed first whether to
raise `KICKSTART_STUCK_UPPER_WINDOWS` (currently 8) given extreme #1
above hit it exactly at the maximum (5/5 possible firings) — user's
own instinct, based on this row's prior history (2026-08-25: three
separate `P=-0.10` attempts, every one flagged stiction, never a clean
repeat), was that this specific point likely isn't reliably severe in
the first place, so raising the cap off one N=1 data point would be
premature. Checked directly instead:

```
run          rpm (first ~1s)            peak    kicks
150332       0,0,0,475,1200             1325    1
150415       0,0,0,525,1225             1275    1
150507       0,0,200,725,1075           1150    0
150547       0,0,0,225,1275             1425    2
150632       0,0,0,350,1250             1350    1
150715       0,0,0,600,1250             1300    1
```

All six landed in the ordinary ~400ms-stuck / 1150-1425rpm-peak /
0-2-kicks band seen at the row's other 8 points — **none** came
anywhere close to the ~1.8-2.0s stall / 2725rpm / 5-kicks extreme case.
Confirms the user's instinct directly: `P=-0.10, I=-0.02` is not a
reliably-severe point, the earlier extreme event was a rare/unlucky
draw at this coordinate, not a reproducible property of it — consistent
with this exact row's already-documented poor reproducibility
(2026-08-25 section above). **Practical consequence: raising
`KICKSTART_STUCK_UPPER_WINDOWS` off this one data point would be
premature** — there's no evidence yet that the cap itself was the
limiting factor for *this coordinate* specifically, since it mostly
doesn't need anywhere near 5 kicks to resolve. The escalation-cap gap
found above remains real (confirmed once, on real hardware), but
tuning a new specific threshold value needs either a genuinely
reproducible severe point to test against, or a broader sweep to find
one — not decided yet, no further action taken this session.

## 2026-08-28: Hall-Position Torque Characterization — New Tool Built,
State 0 Identified as the Worst Position

**Motivation:** the user's hypothesis, raised the same day — stiction
likelihood may depend on *where* the rotor happens to rest (which of
the 6 Hall states, and potentially which of the motor's 4 mechanical
pole-pair repetitions of that state) when a step command arrives, not
just on `P`/`I`. Neither `run_experiment.py` nor
`capture_step_response.py` had ever queried `hal` before a step — a
real, previously unexamined gap. `cntl1mot` (PID `0x04`) turned out to
already be defined in `addresses.json`/handled by firmware (a single
raw, open-loop `driveStep()` pulse, no PI/ramp) but never wired up on
the Python side at all — built fresh this session: `linbus.set_pulse()`,
`watchdog.py`'s new `pulse <value>` verb (own `PULSE_SPEED_MIN/MAX =
±1274`, one below `GLOBALRATE=1275` where `driveState()` itself
silently no-ops — deliberately *not* reusing `speed`'s `SPEED_MIN/MAX`,
a different, tighter policy range for a fundamentally different,
unramped command), and a `kickcount`-style `motorcontrol.py` entry.
Also does **not** feed the rpm-based stall check (`last_commanded_speed`
untouched) — a single probe pulse firing that check 3s later would be
nonsensical.

**Manual probing found the real breakaway range before building
anything automatic — and it directly questioned `KICKSTART_SPEED`
itself:** `pulse 16` (`KICKSTART_SPEED` itself, the exact value the
firmware kick-start already uses) produced only an audible tick, no
real movement. `pulse 600` was audibly stronger but still produced no
permanent movement. `pulse 1000` broke through and kept the rotor
advancing. **This means a single kick-start pulse, at its current
strength, is probably nowhere near strong enough to do the actual work
of breaking stiction on its own** — every past "the kick-start
helped" observation (2026-08-27 sections above) is now more plausibly
attributable to the PI controller's own steadily-rising `controlvariable`
running in parallel, not the kicks themselves. This is a real, still
unresolved tension: `KICKSTART_SPEED` was deliberately kept low
(≈5A, current-limit-derived) for safety, but real efficacy — per this
session's data — looks like it needs something in the 600-1000+ range,
far above that safety target. Not resolved this session; flagged as a
real design question for whenever kick-start tuning resumes.

**Cogging-torque ("Rast") confirmed as a distinct, real phenomenon at
`pulse 750`:** the rotor visibly moved but sprang back to *exactly* the
same position — the signature of a genuine magnetic detent (rotor
permanent magnets vs. stator slot reluctance), not just "too weak a
push." A second, independent effect layered on top of the existing
Dead Zone (weak *commutation* torque near a Hall-sector boundary)
theory — the two can coincide and compound.

**Tool built and iterated live, same session,
`raspi/control/characterize_hall_positions.py`:**
1. First version: single fixed pulse per position, human judged
   "weit/mittel/wenig" by eye. Abandoned once it became clear a fixed
   pulse can't distinguish "sprang back into the same detent" from
   "barely moved at all" — both look identical from a bare `hal`
   reading, and the qualitative judgment couldn't capture the
   spring-back signature at all.
2. Redesigned around an **escalating-threshold search per position**
   instead: read `hal` as reference, fire `pulse` at increasing
   magnitude (defaults 750 start / +50 step / 1100 ceiling, chosen
   from the manual probing above, `SETTLE_S=0.5` between pulse and
   re-read — raised from an initial 0.3s specifically to let the
   mechanical re-detent finish, not just the electrical pulse — see
   the user's own reasoning), until the Hall state *permanently*
   differs from the reference. The threshold value itself is the
   quantitative measurement, no human judgment needed for the core
   loop.
3. **Made fully automatic mid-session**, on the user's own realization:
   since a strong-enough pulse (1000) reliably *drives the rotor
   forward*, the pulse that characterizes one position doubles as the
   transport to the next — no manual repositioning needed between
   measurements at all. The operator now positions the rotor by hand
   only *once*, at the very start; the script then runs
   `NUM_POSITIONS_DEFAULT=24` (6 states x 4 pole-pair repetitions)
   positions completely unattended, stopping early (with a clear
   report, not a silent guess) only if a position fails to break
   through by the ceiling — there's no "next position" to continue to
   in that case. `Ctrl-C` and a mid-run crash both leave every
   already-collected row on disk (`csv.writer` flushed after every
   row) — the script writes its own CSV file directly rather than the
   project's usual "print CSV to stdout, caller redirects" convention,
   specifically because this script's own interactive prompts share
   the same stdout a redirect would otherwise capture, which would
   have interleaved prompts into the data.
4. **`direction` parameter added** (cw/ccw, prompted at startup,
   default cw) — a plain sign flip applied to every pulse sent. One
   run only ever covers one direction; running both means invoking the
   script twice.
5. **`detent_type` prompt added**, asked only when the ceiling is hit
   without a permanent transition: `mittelrast` (shallow detent, easy
   to escape by hand, but the pulse's fixed torque direction may be
   poorly aligned with the escape direction at this exact rotor angle
   — see the Dead Zone reasoning) vs. `tiefrast` (genuinely
   strong/deep). Not distinguishable from `hal`/`attempts` data alone,
   so asked live and logged alongside the current Hall position.

**Companion plotting tool, `analysis/plot_hall_characterization.py`:**
step-plot of `attempts` (escalation steps needed) vs. sequence index,
x-axis labelled with each iteration's starting Hall state, multiple
CSVs overlaid for direct reproducibility comparison, ceiling-hit points
marked with an "x". Read-only, `csv.DictReader`-based (tolerates the
`detent_type` column added after the first plots were made).

**Phase 1 — uncontrolled starting position (2 full 24-position runs,
`characterize_hall_positions_cw_2026-08-28_110732.csv`/`_111732.csv`):**
- **Breakaway threshold is clearly state-dependent and highly
  reproducible for states 1, 2, 4, 5** — identical threshold *and*
  attempt count in both runs: state 1 → 850 (3 attempts), state 2 → 900
  (4), state 4 → 900 (4), state 5 → 750 or 850 (1 or 3, same bimodal
  pattern both times). **State 0 was the exception — 1000 (6 attempts)
  every time in run 1, but only 800-850 (2-3 attempts) in run 2** — a
  real inconsistency, not yet explained (candidate causes: different
  approach history/momentum into state 0 each time, or genuine
  variability specific to this position).
- **Destination state after breakthrough is not fixed by the origin
  state alone** — e.g. state 2 landed on 0 most of the time but on 5
  twice in both runs; state 5 landed on both 1 and 2. Correlates with
  how many escalation attempts were needed to get there (more failed
  attempts beforehand → landed further away) — most likely explained
  by residual momentum/partial movement from the *failed* escalation
  pulses accumulating before the one that finally registers as a
  permanent transition, not a clean single-pulse-in-isolation effect.
  Confirmed live by direct observation the same session: watching the
  rotor during a repeat run, the user saw it visibly skip multiple
  Hall sectors at once on some transitions, not always one — a real
  physical effect, not a measurement artifact.
- **State 3 did not appear once in 48 transitions across both full
  runs** (neither as a starting nor a landing state) — later shown
  *not* to be categorically unreachable (see Phase 1 continued below),
  but clearly rare relative to the other 5 states.
- **Two runs stopped early at the pulse ceiling (1100) without a
  permanent transition** — `_113010` at position 17 (state 2, 8
  escalation attempts, no breakthrough) and `_113328` at position 2
  (state 0, 8 attempts, no breakthrough). The user's live observation
  at these exact stuck points: **easy to move past by hand, but the
  pulses couldn't do it** — the seed of the `mittelrast`/`tiefrast`
  distinction added to the tool afterward. Read as evidence for a pure
  Dead Zone (commutation-torque-direction) failure rather than strong
  cogging: a hand can push tangentially in exactly the needed
  direction; a fixed commutation state's pulse can only push in
  whatever direction that specific winding-current combination
  happens to produce, which may be poorly aligned with the escape
  direction at that exact rotor angle even at high current.
- **Phase 1 continued** (`_112652`, a third full run): state 3 *did*
  appear this time (`2→3`, `3→4`) — refutes "categorically
  unreachable," supports "rare, not impossible."

**The "cut": controlled starting position, from `_114345`/`_114903`
onward.** The user's own root-cause diagnosis of Phase 1's
run-to-run inconsistencies (especially state 0's varying threshold):
the *starting* rotor position before each 24-position run was itself
not being held consistent by hand, confounding every downstream
comparison. Deliberately not treated as invalidating Phase 1's data —
kept, not deleted (already archived locally in
`runs/2026-08-28_hall_characterization/` regardless of what happens to
the Pi's own working copies) — but a clean methodological break before
trusting cross-run comparisons further.

**Phase 2 — controlled starting position (7 runs,
`_114345` through `_115614`):**
- **The controlled start worked exactly as intended: every single run
  begins identically** — state 2, threshold 900, 4 attempts, all 7
  times. Confirms Phase 1's state-2 reproducibility wasn't a fluke and
  that hand-positioning repeatability is achievable when deliberately
  controlled.
- **But even from this identical, controlled start, the destination
  still varies: 5 of 7 runs landed on state 5, 2 of 7 on state 0** —
  same threshold, same attempt count, different outcome. Points to a
  genuine bistability/tie-breaking right at this position's boundary
  (imperceptibly small differences in exact rest angle, or real
  electrical/thermal noise), not something explainable by prior-run
  momentum this time, since it's always the first position in a fresh
  run.
- **State 0 confirmed as the single worst position across this batch:**
  encountered ~7 times, broke through only 3 (inconsistently, at 850,
  1000, and 1000), and **got stuck at the 1100 ceiling 4 times** — a
  roughly 4-in-7 stall rate at this one position, far above every
  other state. **All 4 stuck cases were independently judged
  `mittelrast`, never `tiefrast`** — a consistent, repeated result, not
  a one-off — strong support for the Dead Zone
  (torque-direction-misalignment) explanation specifically at this
  position, over a strong mechanical lock.
- One additional stuck case at state 2 (`_115502`, position 9,
  `mittelrast`) — again a *different* encounter of state 2 than the
  every-run-identical starting one, consistent with the standing
  "different mechanical pole-pair repetition of the same electrical
  state can behave differently" hypothesis (not proven, no absolute
  position reference exists to confirm it directly — see the
  2026-08-28 discussion earlier in this log about why `hal` alone
  can't distinguish which of the 4 repetitions is active).

**Net takeaway so far:** the Hall-position hypothesis is strongly
supported — breakaway difficulty is real, measurable, and (for most
states) reproducible, with state 0 standing out as a specific,
repeatedly-confirmed problem position. Two things remain open: (1) the
real-efficacy-vs-current-safety tension for `KICKSTART_SPEED` raised
by the manual probing above, and (2) CCW characterization — every run
so far has been `cw` only, `ccw` not yet attempted.

## 2026-08-28 (continued): Quarter-Anchored Tracking, Finer Resolution,
and a Cluster of Manual-Testing Findings (Chattering, Reversed Torque)

**The user's own challenge to the state-only analysis above turned out
correct, and led to a real redesign.** Asked directly whether grouping
by "6 states" was even the right frame, given the motor mechanically
has 24 positions — confirmed this is a genuine blind spot: `hal`
readings, and therefore the `%6` cumulative-position math the plotting
tool already used, cannot distinguish *which* of the 4 mechanical
pole-pair repetitions of a state is active, only the electrical state
itself. The user's fix: since only a human with a physical mark on the
shaft can reliably track which quarter is active (watched by eye, not
inferred), have the operator supply the **starting quarter (0-3)**
once per run, then trust the script's own step-accumulation (assumed
never to skip a full extra electrical revolution in one short pulse —
physically plausible, not provable from `hal` alone) to propagate that
quarter number forward for the rest of that one run.

**`characterize_hall_positions.py` redesigned around this:**
- Startup now asks for the starting quarter; a new `quarter` CSV column
  is computed (not measured) from it for every row.
- **A run now characterizes exactly one quarter, not a fixed 24-position
  sweep** — stops once `QUARTER_STEPS=6` electrical states have been
  crossed since the start, deliberately bounding how far the unverified
  step-accumulation assumption has to hold before the operator
  re-anchors by hand (same one-confirmed-unit-then-stop spirit as
  `run_grid_row.py`'s row consent model).
- **Extended the same day**, after the user found a mittelrast sitting
  right at a quarter boundary that a hard stop-at-6 would have missed:
  the run now continues up to `BONUS_ATTEMPTS_AFTER_BOUNDARY=2` more
  positions past the boundary specifically to catch that. A normal
  (non-stuck) bonus-round transition is deliberately **not** written to
  the CSV — its estimated quarter is past the operator's anchor point,
  not trustworthy data — only a stuck result during the bonus round is
  recorded.
- **`PULSE_STEP_DEFAULT` lowered 50 → 25`** — now that a run covers one
  quarter instead of 24 positions, finer resolution costs proportionally
  less total time.
- Plotting tool gained a many-file overlay mode (>8 files): all traces
  drawn in one translucent color instead of a per-file legend — genuine
  reproducibility shows up directly as darker/opaque overlapping
  segments, divergent paths stay faint. Built specifically because a
  16-file batch with per-file colors was unreadable.

**Phase 3 results — 16 quarter-0 runs, finer resolution
(`characterize_hall_positions_cw_q0_*.csv`):**
- **The first two thresholds converge precisely and identically across
  all 16 runs: state 2→5 at 875 (6 attempts), state 5→(1 or 2) at 825
  (4 attempts) — both exact, no spread at all.** The earlier "bimodal
  750-or-850" reading for this same transition (Phase 1/2, 50-step
  resolution) is now understood as a coarse-grid artifact straddling
  this one true value, not real bimodality.
- **The "second visit to state 2" finding, now with a much larger
  sample:** of the runs whose path went state 2 → 5 → 2 (back to state
  2 a second time within the same run), roughly half got stuck for the
  *entire* escalation ceiling (15 attempts at the finer 25-step
  resolution) immediately afterward, every one flagged `mittelrast`.
  The always-clean *first* visit to state 2 (position 1 of every run,
  875/6 attempts, never stuck) versus the unreliable *second* visit is
  the clearest evidence yet that these are genuinely different
  mechanical instances of the same electrical state, not the same
  physical spot behaving inconsistently.

**Manual follow-up testing (via `motorcontrol.py`'s new `pulse`
command directly, not the automated script) produced a cluster of
significant findings the same session:**

1. **Direct, hand-verified confirmation of quarter-dependent behavior.**
   State 4 (`[0x1,0x0,0x0]`) — one of the most reliable states in the
   Q0 data, always breaking through cleanly at 900/4 attempts, never
   once stuck — got stuck in a mittelrast under `pulse 1000` (stronger
   than the Q0 value that always worked) while in **quarter 1**. Same
   electrical reading, different quarter, clearly different real
   behavior — not inferred this time, directly observed.
2. **Occasionally reversed effective torque, not just weak torque.**
   At that same stuck spot, the user observed the rotor visibly moving
   **CCW** under `pulse 1000` (a positive, CW-signed command) in some
   attempts. Plausible mechanism: if the true magnet angle has drifted
   far enough from the Hall reading's "expected" position, the
   commanded commutation phase can fall past the torque curve's zero
   crossing, producing net torque in the *wrong* direction even though
   the correct (CW) state was commanded. This is the first concrete,
   observed motivation for the bidirectional kick-start idea discussed
   the previous evening (2026-08-27) — escalating a single-direction
   pulse can't help, and may actively hurt, at a position where the
   commutation torque itself points the wrong way.
3. **Root cause found for the inconsistent behavior at that spot:
   Hall-sensor chattering right at the Tiefrast/Mittelrast transition.**
   Reading `hal` repeatedly with no pulse in between, at that exact
   resting position, flickered between `[0x1,0x1,0x0]` (state 3) and
   `[0x1,0x0,0x0]` (state 4) — the rotor wasn't moving, but the Hall
   sensor's digital output was toggling between two adjacent electrical
   readings, almost certainly from insufficient hysteresis at its
   switching threshold when the magnetic field sits right on the
   boundary. Named: **chattering** (a threshold/switching-boundary
   oscillation, not a software race condition, though the observable
   effect — outcome depends on unlucky timing of the read — feels the
   same). Directly explains findings 1 and 2 above: `driveStep()`/
   `driveStepKickStart()` compute their target state fresh from
   whatever `hal` returns at that instant, so the *same* physical rotor
   position can issue two *different* commutation commands purely
   depending on which side of the chattering threshold got sampled.
4. **Refined further by manual stepping: the Hall switching threshold
   sits inside the Mittelrast itself, not cleanly at the mechanical
   Tiefrast/Mittelrast boundary.** Turning by hand from a Tiefrast into
   the following Mittelrast usually still reads the Tiefrast's old Hall
   value throughout the Mittelrast, but occasionally flips early to the
   next state's value while the rotor is still mechanically captured in
   the Mittelrast. Consequence: a bare `hal`-based "did it transition"
   check can be fooled into believing a breakthrough happened when the
   rotor is mechanically still trapped — a real measurement-validity
   caveat for every threshold value gathered by this whole
   investigation, not just an isolated curiosity.
5. **User's own independent, repeated physical finding (by feel, not
   inferred): mittelrasten always sit between tiefrasten** — a
   structural, repeating cogging pattern around the rotor, not
   occasional/random weak spots. Consistent with normal cogging-torque
   physics (multiple ripples per electrical sector are common,
   depending on pole/slot count) but now confirmed specifically for
   this motor by direct touch, independent of any electrical
   measurement.

**Net effect on the whole investigation:** what started as "does
starting position affect stiction" has surfaced a genuine, specific
hardware-level finding (Hall sensor chattering at sector boundaries,
compounded by quarter-to-quarter mechanical variation) that plausibly
explains much of the run-to-run unpredictability seen throughout this
whole project's stiction investigation — not just a P/I tuning
question. Not yet resolved: whether the chattering is inherent to this
specific Hall sensor/mounting (fixable only mechanically) or could be
mitigated in firmware (e.g. requiring N consecutive identical readings
before trusting a state change — a debounce, conceptually related to
the already-open `_detect_stiction()` blip-handling bug). CCW
characterization still not started.

**Same-day follow-up discussion: `KICKSTART_SPEED` reconsidered in
light of today's whole characterization effort — decision deliberately
deferred to next week, thoughts captured here only.** The user pointed
out `driveKickStart()` has been driving every real kick with
`KICKSTART_SPEED=16` this whole time, which today's own data shows
could never have worked as a single-pulse breakaway mechanism — every
measured threshold today (750-1000+, some positions not breaking
through even past 1100) is far above it. Naive duty-cycle current
estimate at the higher end (`pulse 1000`) is ≈325A, nominally alarming
against the original 5A safety target — but the user has been running
real hardware at 750-1100+ repeatedly all session (dozens of pulses
across many positions) with no observed damage, real empirical
evidence the theoretical estimate may be overly conservative for a
pulse this brief (~1.3ms). Caveat noted: current sensing is still
disabled (known hardware issue), so "no visible damage" isn't the same
as "current stayed low" — absence of failure, not a measurement.
**Considered raising `KICKSTART_SPEED` to 800 — checked against
today's data and flagged as likely insufficient:** state 2→5 (the
single most common and most reliably measured transition today, exact
875 in all 16 Q0 runs) would still not break through in one shot at
800. 900-950 would cover that specific case with margin; no fixed
value covers everything found today (quarter 1's >1100 no-breakthrough
case). **No firmware change made — explicitly a next-week decision**,
the user edits `main.c` themselves.

**One more nuance raised right after, worth weighing against the
2026-08-27 conclusion that `KICKSTART_SPEED=16`'s real-world
"successes" were probably all the PI controller, not the kicks:** the
`pulse 16` finding ("barely moves the rotor") only means it produces
no *measurable full sector transition* — today's whole characterization
method is Hall-state-based and therefore structurally blind to any
sub-sector displacement (a shift from one point in a detent to another
nearby point, without crossing the electrical boundary). A weak kick
could still be nudging the rotor's exact resting position within its
current detent, without registering as movement at all, potentially
leaving it better-positioned for whatever acts next (the ongoing PI
effort, or a later escalation step) even though the kick itself never
shows up as a breakthrough. Not verifiable with Hall-only
instrumentation — would need close visual/physical observation during
a `pulse 16` event specifically to check for any sub-sector shift.
Not investigated further this session, captured for next week.


## 2026-09-10 - P/I search concluded

**The manual P/I grid/row search is done.** `KPDEFAULT`/`KIDEFAULT` in
`main.c` were changed `0.15`->`0.19` / `0.4`->`0.44` (the old-delta-space
point `P+0.04 / I+0.04`) and flashed -- the firmware default now *is*
that point, no `pi` delta needed to reach it. Chosen pragmatically by
the user: roughly halfway between the old firmware default `(0,0)` and
the heatmap's best point `P+0.04 / I+0.08`, leaning toward the default
for safety, and consistent with root `CLAUDE.md`'s Candidate Selection
Philosophy -- `I` deliberately pulled back from the ISE optimum for
future-load margin; `P` a touch below the best-looking value (could
have gone higher, `P` is protective under load, not risky, but the
user preferred to stay near the known-good).

**Validation:**
- 3 repeatability runs at `pi 0.04 0.04` on the *old* firmware, then 3
  at the *new* baked-in default (`runs/2026-09-10_pi_repeat/`,
  `runs/2026-09-10_pi_repeat_newfw/`). Scored with `run_grid.py`'s exact
  ISE/MSSD functions.
- New-firmware default, n=3 mean: **ISE 1,558,542 / MSSD_2s 41,227 /
  MSSD_full 11,734.** Old heatmap `+0.04/+0.04` cell (n=1): ISE
  1,618,750 / MSSD_2s 55,069 / MSSD_full 14,853. **ISE agrees to ~4%**
  -- the comparison holds. MSSD read a bit *lower* (smoother) on the new
  runs, but that is within n=1-vs-n=3 run-to-run noise plus two small
  method changes that favour the new runs (`capture_step_response.py`
  now does a `reset` before the step, clearing integral windup;
  manual vs. `run_grid.py`'s enforced 4s inter-run pause) -- not a
  claimable improvement over the heatmap value, just consistency.
- Old firmware default `(0,0)` was ISE ~2,133,125, so the new default
  is **~27% better on ISE** and sits at the smooth end of the good
  region. User-confirmed by ear: no roughness ("kein Ruppeln"); a mild
  overshoot in the ~650-900 rpm band during the rise, present in the
  LIN trace, clearest in one of three runs.

**No big jumps -- and that is the honest outcome.** The measured
improvement over the old default varied 7-30% across repeats
(comparable to run-to-run noise); nothing has been tested under the
eventual ~50kg vehicle load (which moves the optimum anyway); and
finite-difference gradient search was already ruled out (noise at
small steps). What the grid search *did* establish solidly: more `P`
is better, `I` barely matters within the good region, do not go past
`P` about +0.10 (audible-roughness boundary). A conservative,
validated, documented point inside that region is the right place to
stop.

---

### Fazit of the 2026-09-07 -> 09-10 arc

**The P/I number was the minor part.** What got built alongside it
matters far more:

- **A LIN bug found and fixed.** `cntl1mot`'s multi-`driveStep()` pulse
  handler blocked the STM32 main loop ~5ms per call -- long enough for
  the Pi watchdog's independent background poll to land a byte in the
  gap, a UART overrun that left the STM32 **permanently deaf until a
  physical reset** (confirmed via `watchdog.log`). Fix: a
  `HAL_UART_ErrorCallback` override (clear ORE/FE/NE, reset state, set
  `sysError=LIN_RCV_ERR`, `HAL_UART_AbortReceive` then re-arm -- the
  explicit abort was load-bearing). See `STM32/CLAUDE.md`'s Status
  section.

- **Stall handling, end to end.** `driveKickStart()` simplified (one
  pulse per window, escalation loop gone). New `reset` command + 6-byte
  `status` with `sysError` -- firmware-state visibility that did not
  exist before, useful well beyond stalls. `burst` -- a new tunable
  Pi-side reverse-then-forward pulse primitive. And the insight behind
  it: `pulse` magnitude changes current/duration, *not* commutation
  angle, so "try harder" cannot break a Mittelrast -- a *different*
  torque vector is what is needed.

- **A reproducible test case for a previously-random failure.** Pushing
  the rotor into the 010/110 Mittelrast reproduces the stall on demand
  -- the precondition for studying it at all.

- **Automatic stall detection + recovery in `capture_step_response.py`.**
  Mid-run: `rpm=0` at ~1s + `status` confirms `STALL_TIM_ERR` -> a
  random recovery sequence from a fixed catalog (`speed`/`pulse`/
  `burst`, 2-3 steps, deliberately conservative constraints after the
  MOSFET failure) -> the whole step retried as the success test. Every
  attempt logged two-phase to `recovery_sequences.csv` (raw values,
  not success/fail labels -- the analysis tool decides, and can
  re-decide later). Already producing real training data for the
  planned decision-tree (see `raspi/watchdog/CLAUDE.md`).

- **A hardware failure turned into understood constraints.** Two
  MOSFETs burned (`KICKSTART_SPEED=800` overcurrent into a stalled
  winding). Root-caused by close code reading (overcurrent, not a
  shoot-through logic bug), then `KICKSTART_SPEED` cut to ~127, `Plus`
  disabled, margins added -- a documented safety envelope, not just a
  parts swap.

- **Knowing when to stop.** The CW/CCW state-table asymmetry was dug
  into, the hand-measurements contradicted each other, and it was set
  aside -- trusting `driveStep()`'s years of validated behaviour over a
  confusing bench measurement, and deciding the open question blocks
  nothing. Same discipline that concluded the P/I search: stop at
  "good enough, validated, documented" rather than chase noise.

- **Cleared a second-motor prerequisite by checking, not building.**
  The multi-instance `hwbits` LIN dispatch turned out already complete
  in `main.c` -- a stale "not yet done" in the docs, now corrected in
  both root `CLAUDE.md` and `STM32/CLAUDE.md`.
