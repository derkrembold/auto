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

## STM32 — not yet triaged

1. Re-verify SW1-4/PB14-PB15↔J1 pin mapping facts against `demoboardV2` specifically (unresolved labeling ambiguity)
2. Implement Hall-based local stall detection (now unblocked, build/flash are headless)
3. `KICKSTART_SPEED` — revisit raising it again more cautiously (currently reduced after MOSFET burnout)
4. Hall-sensor chattering — decide/implement firmware debounce (or confirm it's a hardware/mounting limitation)
5. CW/CCW state-table asymmetry — still unresolved (set aside, not fixed)
6. Firmware-side sanity clamp on KP/KI + status readback of currently-applied KP/KI values
7. Dedicated rpm-based before/after proof that a corrupted nonzero-speed write has zero effect on real setpoint
8. Systematically pulse-test all 24 mechanical positions (Tiefrast + Mittelrast) — now unblocked
9. Deterministic `selftest` provocation for the UART receive-error path (deferred, timing race)
10. `STM32/notes.md`'s file-tree section needs re-verification against corrected `demoboard` source
11. Known race in `main.c:303` timeout check (non-atomic read) — minor, open

## currentsensor — not yet triaged

1. Add hardware instance-strap-pin reading (like motor's `hwbits`) — needed once a 2nd current sensor joins the bus
2. Characterize ACS712 near-0A noise floor properly (`CURRENT_STALL_THRESHOLD` currently just a guess with headroom)
3. Per-channel calibration for chip-to-chip offset/gain tolerance between the two ACS712s (deliberately deferred)
4. `validate_motor_currentsensor.py` doesn't assert values are close to 0A when stopped — only sanity-bounds raw range

## lightsensor — not yet triaged

1. Add `addresses.hpp`/address table once this slave's PID is assigned
2. Add checksum/echo-compare + sync-scan-loop fix (`currentsensor` already has this)
3. Verify/adapt the hardware design this firmware assumes
4. Set up/test flash environment (avrdude/programmer) from this repo

## raspi (control) — not yet triaged

1. `linbus.py`'s `Lin.write()`/`read()` return bare magic-number error codes — replace with named constants/enum
2. `validate_speed.py`/`capture_step_response.py` silently swallow `ret!=0` reads (prints "None" instead of flagging)
3. Detailed per-command LIN trace for a recovery attempt only lives in rotating `capture_step_response.log` — lost after ~2 more runs

## raspi/watchdog — not yet triaged

1. Hardware kill-switch/relay backstop — needed for the case the watchdog process itself fails
2. Concrete current-cutoff threshold + exact polling rate refinement for the current sensor
3. Individual safety paths (disconnect/idle-timeout/stall) never gezielt einzeln live getestet
4. Client-side correlation ID — revisit if protocol ever stops being strictly one-command-at-a-time
5. "Testsuite bei jeder Änderung"-Regel — Disziplin lassen oder zu echtem Pre-Commit/CI-Hook machen?
6. `on_disconnect()`/`check_idle()` stoppen weiterhin nur Motor 0, nicht alle — bewusst offen gelassen bei §6.3
7. Current-Stall-*Signatur* (observe-only) auf mehr als nur val1/Motor 0 ausweiten
8. Das große geplante Multi-Process-Redesign (Joystick/Learning-Algorithmus/Logging-DB/Web-UI) — eigenes Epic?

## analysis — not yet triaged

1. Exaktes ISE-Fenster + Umgang mit 25rpm-Quantisierung/Window-Lag festlegen (noch nicht implementiert)
2. Mechanismus, um Saleae-Ground-Truth in der Gradient-Search-Phase wieder einzubauen — nicht entschieden
3. MSSD-Werte mit echten Ohr-Beobachtungen auf zukünftigen Läufen abgleichen — bisher nur 1 Anker
4. `grid_heatmap.py` gegen echte Hardware-Daten laufen lassen (bisher nur synthetisch getestet)

## saleae — not yet triaged

1. Sample-Rate für Hall-Kanäle festlegen (Kommutierungs-Timing bei Max-RPM vs. Capture-Größe)
2. Headless-Modus (`Manager.launch()` statt `Manager.connect()`) — diskutiert, nicht gebaut

## Next Session

Pick up at **STM32** — walk through the 11 candidates the same way root
was done (keep/remove/discuss per number), then create the resulting
Issues + update `STM32/CLAUDE.md`'s Open Points accordingly.
