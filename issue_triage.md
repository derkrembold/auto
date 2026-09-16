# GitHub Issue Triage — Working List

Candidate list for turning `CLAUDE.md` "Open Points" entries into GitHub
Issues (repo `derkrembold/auto`, "Auto" project:
https://github.com/users/derkrembold/projects/2). Numbered per
subsystem so the lists stay short — not turned into Issues until the
user says which numbers to pick.

**Process, already set up (2026-09-15):**
- 8 subsystem labels: `root`, `stm32`, `currentsensor`, `lightsensor`,
  `raspi`, `watchdog`, `analysis`, `saleae`.
- `long-term` label for items that only make sense after other
  near-term work lands (e.g. a 3rd/4th motor) — still tracked as a
  real Issue, just separated from the near-term list. Split into
  concrete sub-issues later once they become actionable, not now.
- Once an Open Points bullet becomes an Issue, replace the bullet's
  prose with a short "see Issue #N" reference in the relevant
  `CLAUDE.md` — don't duplicate the description in both places.
- Project board: group by Labels for a per-subsystem view (Project →
  "..." / group icon → Group by → Labels — not settable via API,
  manual one-time UI step).

## Root / Cross-Cutting — DONE (2026-09-15)

1. ~~8S vs 9S battery decision~~ — removed, not tracked.
2. **Issue #1** — [Wire runtime instance-jumper read into currentsensor/lightsensor firmware](https://github.com/derkrembold/auto/issues/1) (`root`)
3. ~~speed≈rpm battery-voltage-drift validation~~ — removed, unclear how to validate.
4. **Issue #2** — [Third/Fourth Motor Support](https://github.com/derkrembold/auto/issues/2) (`root`, `long-term`)
5. **Issue #3** — [IFM Sensor Suite](https://github.com/derkrembold/auto/issues/3) (`root`, `long-term`)

`CLAUDE.md` already updated to reference #1/#2/#3 instead of describing
these inline.

## raspi (control) — extra item, raised directly by the user (2026-09-15)

- **Issue #4** — [capture_step_response.py: dual-motor launch with stop-both-on-stall + retry](https://github.com/derkrembold/auto/issues/4) (`raspi`)
  — launch both motors as parameters, one command; stop both on either's
  confirmed stall; run the existing recovery sequence against the
  stalled one; retry both together. `raspi/CLAUDE.md` already references
  it. Open design questions (target-speed sync, recovery scope,
  CSV/log schema) are in the Issue body, not decided yet.

## STM32 — DONE (2026-09-16)

1. **Issue #5** — [Re-verify SW1-4 / PB14-PB15↔J1 pin mapping against demoboardV2](https://github.com/derkrembold/auto/issues/5) (`stm32`)
2. **Issue #8** — [STM32-local Hall-based stall detection](https://github.com/derkrembold/auto/issues/8) (`stm32`) — flagged as lower priority than it reads, given the Pi-side watchdog already covers this via multiple layers
3. ~~`KICKSTART_SPEED` revisit~~ — not needed, no Issue (stays as narrative caveat in `STM32/CLAUDE.md`'s Known Hardware Issue section)
4. ~~Hall-sensor chattering debounce decision~~ — not needed, no Issue (stays as narrative caveat in the Planned Redesign section)
5. ~~CW/CCW state-table asymmetry~~ — **found moot while triaging**: `driveStepKickStartMinus/Null/Plus()` are dead code (no callers anywhere in `main.c`, confirmed via grep) since `driveKickStart()`'s 2026-09-09 simplification. `STM32/CLAUDE.md` had a stale claim that the question was "still live" there — corrected. No Issue.
6. **Issue #6** — [Firmware-side KP/KI sanity clamp + status readback of applied values](https://github.com/derkrembold/auto/issues/6) (`stm32`)
7. ~~Dedicated rpm-based checksum-gate proof~~ — not needed, strong incidental real-hardware evidence already exists (rpm tracked smoothly through a corrupted write with no dip). No Issue, narrative in Status section unchanged.
8. ~~Pulse-test all 24 mechanical positions~~ — not needed, no Issue. Removed from `STM32/CLAUDE.md`'s Open Points (was the only unresolved item in the "2026-09-07 high-priority list" block, which was otherwise all done — whole block removed).
9. ~~Deterministic `selftest` provocation for UART receive-error~~ — not needed, no Issue. Root cause already fixed+confirmed, triggering condition independently fixed too (`burst`). Stays in Open Points as a documented, deliberately-deferred item (not removed — has a real "revisit if X" trigger).
10. **Issue #7** — [Re-verify STM32/notes.md's file-tree section](https://github.com/derkrembold/auto/issues/7) (`stm32`)
11. ~~`main.c:303` non-atomic race~~ — not needed, no Issue. Minor, already documented as "known accepted" in the Status section, left unchanged.

	## currentsensor — DONE (2026-09-16)

1. **Issue #9** — [Add hardware instance-strap-pin reading to currentsensor firmware](https://github.com/derkrembold/auto/issues/9) (`currentsensor`)
2. ~~Characterize ACS712 near-0A noise floor properly~~ — not needed, chip's inherent tolerance is high enough that precise characterization isn't worth it. No Issue.
3. ~~Per-channel calibration between the two ACS712s~~ — not needed, same reasoning as #2 (high inherent chip tolerance). No Issue.
4. **Issue #10** — [validate_motor_currentsensor.py: assert near-0A when motor is stopped](https://github.com/derkrembold/auto/issues/10) (`currentsensor`) — scoped as a cheap regression sanity check reusing the existing approximate threshold, not new calibration work (distinct from #2/#3 above)

## lightsensor — DONE (2026-09-16)

Merged into **one** issue rather than four — the firmware is only
DCPS-course-project fragments, not real working code, so "add
addressing" and "add checksum/echo-compare" aren't separable patches on
top of something real, they're just facets of the one real task: write
the actual firmware.

1. ~~Add addresses.hpp once PID assigned~~ — folded into the write-the-
   firmware issue below. `addresses.json` already reserves the PID
   (`cntl0lig`/`st0lig`), just needs `generate_addresses.py` to target
   this folder too.
2. **Issue #11** — [lightsensor: write the real firmware (LIN addressing + checksum/echo-compare)](https://github.com/derkrembold/auto/issues/11) (`lightsensor`)
3. ~~Verify/adapt the hardware design~~ — not needed as a standalone item, naturally happens once real firmware + real hardware are brought up together. No Issue.
4. ~~Set up/test flash environment~~ — not needed, no Issue. Flashing is always manual (same convention as `currentsensor`, see the `avr_flashing_manual` memory) — no flashing tooling gets built for either.

## raspi (control) — DONE (2026-09-16)

1. **Issue #12** — [linbus.py: replace bare magic-number error codes with named constants](https://github.com/derkrembold/auto/issues/12) (`raspi`)
2. **Issue #13** — [validate_speed.py/capture_step_response.py: flag conspicuously on ret!=0 reads](https://github.com/derkrembold/auto/issues/13) (`raspi`)
3. **Issue #14** — [Increase number of rotating logs](https://github.com/derkrembold/auto/issues/14) (`raspi`) — renamed from the original framing (detailed recovery-attempt trace lost after ~2 runs) to the actual fix direction: `logsetup.py`'s rotation currently keeps only 1 generation, shared by all four `raspi/` scripts

## raspi/watchdog — DONE (2026-09-16)

1. **Issue #15** — [Hardware kill-switch/relay backstop for watchdog process failure](https://github.com/derkrembold/auto/issues/15) (`watchdog`)
2. ~~Current-cutoff threshold + polling rate~~ — **found stale while triaging**: this predates the 2026-09-10 overcurrent-hard-stop build, which already has a concrete threshold (15A, reasoned against the ACS712's linear range + motor's rated draw) and polling rate (1.0s). No Issue, bullet removed from `raspi/watchdog/CLAUDE.md`'s Open Points as resolved.
3. **Issue #16** — [Deliberately, individually live-test each watchdog safety path](https://github.com/derkrembold/auto/issues/16) (`watchdog`)
4. ~~Client-side correlation ID~~ — not needed, still correct as originally reasoned (protocol still strictly synchronous even with 2 motors). No Issue.
5. ~~Test-suite-as-discipline vs. CI-hook~~ — decided: stays discipline, no CI hook. No Issue, `raspi/watchdog/CLAUDE.md` updated to state this as a decision rather than an open question.
6. **Issue #17** — [on_disconnect()/check_idle() should stop ALL motors, not just motor 0](https://github.com/derkrembold/auto/issues/17) (`watchdog`) — flagged as a real safety-consistency gap, not outdated: stall/overcurrent already stop all motors (§6.3), disconnect/idle-timeout still don't
7. **Issue #18** — [Extend current-stall signature check beyond val1/motor 0](https://github.com/derkrembold/auto/issues/18) (`watchdog`) — normal priority, not high (still observe-only, no safety action gated on it)
8. Split into two: **Issue #19** — [Joystick input process](https://github.com/derkrembold/auto/issues/19) (`watchdog`, near-term) and **Issue #20** — [Long-term: Learning Algorithm + Logging Database + Web UI](https://github.com/derkrembold/auto/issues/20) (`watchdog`, `long-term`)

Also found and removed while triaging: `raspi/watchdog/CLAUDE.md`'s
"Blocked on STM32/CLAUDE.md's Planned Redesign" Open Points bullet
(reset/status verbs it described as "not started" have been built and
confirmed since 2026-09-07/08) — stale, not part of the 8 candidates,
fixed opportunistically.

## analysis — DONE (2026-09-16), all dropped, no Issues

All four not needed — P/I search concluded 2026-09-10, no follow-up
gradient-search phase is happening (already judged a poor fit), and
Saleae's role in the project is diminishing. `CLAUDE.md`/
`analysis/CLAUDE.md` updated accordingly.

1. ~~Exact ISE window + 25rpm-quantization/window-lag handling~~ — not needed, the metric as-is was good enough to conclude the search.
2. ~~Saleae ground-truth reintroduction for gradient-search~~ — not needed, that phase isn't happening; also Saleae's importance is decreasing generally.
3. ~~MSSD vs. by-ear observation pairing~~ — not needed, stakes dropped along with the concluded search. (Note: this item actually lived in root `CLAUDE.md`, not `analysis/CLAUDE.md` — corrected while triaging.)
4. ~~Run `grid_heatmap.py` against real hardware data~~ — **found already done while triaging**: it was run against real data 2026-08-25 (108 coordinates, 126 measurements, the run that surfaced the `P+0.04/I+0.04` candidate). `analysis/CLAUDE.md` had a stale "not yet run against real data" claim — corrected.

## saleae — DONE (2026-09-16), both dropped, no Issues

Same reasoning as `analysis`'s list — Saleae's role in the project is
diminishing (P/I search concluded, no gradient-search phase where
ground truth would have mattered more).

1. ~~Sample rate for Hall channels~~ — not needed. No Issue.
2. ~~Headless mode~~ — not needed. No Issue.

`saleae/CLAUDE.md` updated accordingly.

## Triage Complete (2026-09-16)

All 7 subsystems + root/cross-cutting triaged. Final tally: **20
Issues** created (`derkrembold/auto`, "Auto" project), split across
`root`(3) `stm32`(4) `currentsensor`(2) `lightsensor`(1) `raspi`(4)
`watchdog`(6), 3 of them also `long-term`. Several stale Open Points
bullets and one dead-code claim were found and corrected along the way
(see the per-subsystem sections above for each).

This file's job is done — the remaining "what's open" tracker going
forward is the GitHub Issues list itself, not this file. Keep it around
as a historical record of the triage session, or delete it — not a
living document to maintain further.
