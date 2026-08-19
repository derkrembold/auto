# saleae — Context for Claude Code

This folder holds the Saleae Logic Pro 16 capture configuration and
exported captures for the BLDC motor speed measurement setup described in
the root `CLAUDE.md`.

## Purpose

The Saleae records the motor's 3 Hall sensor channels plus a trigger
channel (4 channels total), non-invasively — tapped off signals the
firmware already needs for commutation, no firmware changes required.
Speed is computed in software from the time between Hall edge transitions
(see `analysis/`). This replaces LIN-based measurement readback entirely —
the Raspi/LIN side is control-only now.

## Structure

- `capture_config/` — channel mapping, trigger setup, sample rate for the
  Saleae capture.
- `exports/` — raw capture exports, one per test run, paired with that
  run's parameter set/metrics under `runs/`.

## MCP Server (`saleae_mcp/`)

**Built and confirmed working 2026-08-17.** An MCP server wrapping the
Saleae Logic 2 Automation API (`logic2-automation`, imported as `saleae
.automation`), so Claude Code can drive captures directly instead of the
user operating the Logic 2 GUI by hand — `saleae_mcp/server.py`, registered
project-wide via `claude mcp add --scope project` (see repo-root
`.mcp.json`). Newly added MCP servers need a one-time approval prompt in
Claude Code before their tools become callable.

**Lives in `saleae_mcp/`, not `saleae/`, deliberately.** The installed
`saleae` package (providing `saleae.automation`) and this repo's own
`saleae/` folder are both Python namespace packages with the same name —
importing from the repo root merges them. Keeping server code out of
`saleae/` avoids any ambiguity about which "saleae" an import resolves to;
`saleae/` itself stays exactly as before (`capture_config/`, `exports/`).

**Headful by design, for now** (discussed 2026-08-17): the server calls
`automation.Manager.connect(port=10430)` against an already-running Logic 2
instance, not `Manager.launch()` — lets captures be watched live in the
GUI while Claude Code drives them. Logic 2's Automation API server has to
be enabled first, one of:
- GUI: Preferences → scroll all the way to the bottom → the automation
  server checkbox (easy to miss, not near the top).
- Command line: launch Logic 2 with `--automation --automationPort 10430`.
Either way requires an app restart to take effect if Logic 2 was already
running without it — toggling the checkbox on a live instance doesn't
retroactively open the port. A fully headless mode (`Manager.launch()`,
no GUI needed at all) was discussed as a real future option once the
current setup is proven out, not built yet.

**Gotcha hit while building this:** `pip install mcp` currently installs
2.0.0, which renamed `FastMCP` (`mcp.server.fastmcp.FastMCP`, the name
used in virtually all existing tutorials/examples) to `MCPServer`
(`mcp.server.mcpserver.MCPServer`) — same interface (`.tool()` decorator,
`.run()`), just a different import path. `server.py` already uses the new
path; if a tutorial or AI-generated snippet references `FastMCP`, that's
why it won't import against what's actually installed here.

**Tools exposed:** `list_devices`, `start_capture` (modes: `manual` —
runs until `stop_capture()`; `timed` — fixed `duration_seconds`;
`trigger` — digital edge/pulse on a channel, matches this project's
hardware trigger pin, see root `CLAUDE.md`'s Data Flow section, no
software sync needed; `min_pulse_width_seconds`/
`max_pulse_width_seconds` also accepted for `pulse_high`/`pulse_low`,
but see the Trigger pin Open Point below — that trigger type doesn't
actually fire via this API, don't rely on it), `wait_for_capture`,
`wait_for_capture_or_timeout` (added 2026-08-18 — always prefer this
for `trigger` mode, see its docstring for the hung-Logic-2 failure mode
it exists to prevent), `stop_capture`, `export_capture` (raw CSV into
`saleae/exports/<name>/`), `save_capture` (native `.sal` into
`saleae/exports/`), `close_capture`. Deliberately generic/parameterized
(channel indices, sample rate, trigger settings all passed in per call)
rather than hardcoded to this project's specific pin mapping.

**`close_manager()` (plain function, not an `@mcp.tool()`, added
2026-08-19)** — closes the underlying `automation.Manager.connect()`
connection. Found live: `run_experiment.py` (root `CLAUDE.md`) never
called this, and the connection (gRPC underneath) kept the Python
process alive after `main()` returned — the script needed Ctrl-C to
actually exit even after finishing successfully. Not an MCP tool
because it's a standalone-script lifecycle concern, not something
meaningful for Claude to call over its own MCP session (that
connection's lifecycle is managed by the MCP protocol layer, not by
calling a function inside this module). Any future standalone script
using `server.py` directly should call this in a `finally` block
around its `main()`, same pattern `run_experiment.py` now uses.

**Confirmed working (2026-08-17)** against the Automation API's built-in
`LOGIC_PRO_16` simulation device (`device_id='F4241'`, no real hardware
needed for this level of test): full lifecycle in all three capture
modes (`manual`+`stop_capture`, `timed`+`wait_for_capture`,
`trigger`+`wait_for_capture`), plus `export_capture` (real multi-channel
`digital.csv`) and `save_capture` (real `.sal`) verified by reading the
files back off disk, not just trusting a non-error return. The real
Logic Pro 16 (`device_id='DB59F8F22EA91DEA'`) is now also exercised
through a full real capture (2026-08-17, `timed` mode, 20s, channels
0-3 at 10MHz) — see the Trigger pin Open Point below for what it
captured.

**Operational lesson, hit repeatedly:** *any* capture (not just
`manual` mode — this also bit a `trigger`-mode capture twice, live,
2026-08-18) that's started but never reaches
`stop_capture()`/`close_capture()` (calling process killed, a
`wait_for_capture()` call abandoned via a tool timeout, trigger
condition that never fires) leaves Logic 2 stuck "recording" — every
subsequent `start_capture()` fails immediately with
`InternalServerError: Cannot switch sessions while recording`, and
there's no clean API call to reach or stop that orphaned capture from a
new connection. Only fix found: manually click stop in the Logic 2 GUI
(or restart Logic 2 entirely). `wait_for_capture_or_timeout()` (see
above) exists specifically so `trigger`-mode code never has to risk
this — always prefer it over bare `wait_for_capture()` when the trigger
condition isn't guaranteed to fire.

## Physical Pre-Flight Checklist

Manual steps needed before *any* capture (timed or trigger mode) — none
of this is automatable from `saleae_mcp/server.py`, it's physical/GUI
setup on the Windows host:

1. STM32 target actually running — `flash.sh` without `--reset` leaves
   it halted (check `STM32/flash.log`'s last line). Reset via SW2, or
   have Claude run `flash.sh --reset` (separate consent event).
2. Logic 2 GUI running with the Automation API server enabled
   (Preferences → bottom → automation server checkbox — see the MCP
   Server section above). Needs an app restart if it was off.
3. Saleae Logic Pro 16 connected via USB.
4. Motor power supply/battery switched on — without it the motor can't
   turn regardless of firmware/LIN state, see root `CLAUDE.md`'s
   Battery section.
5. Wiring check: channels 0-2 on H1/H2/H3 (`J2`), channel 3 on the
   trigger pin (`GPIO_PIN_12`, `J1`) — see the Open Points below for
   the mapping.
6. Watchdog running `--live` on the Pi (check/restart over SSH if the
   session isn't still open from a previous test).

## Open Points (Saleae-specific)

- **Hall channel mapping — resolved (2026-08-17).** Board nets `H1`/`H2`/
  `H3` (routed out to connector `J2`) are confirmed 1:1 against the
  `demoboardV2` PCB netlist to be `PC0`/`PC1`/`PC2` respectively — see
  `STM32/CLAUDE.md`'s Hardware section for the exact pad/net evidence.
  Tap these three off `J2` for the Saleae's Hall channels.
- **Trigger pin — wired and confirmed working under `timed` mode
  (2026-08-17).** `GPIO_PIN_12`/`GPIOB`, off connector `J1`. Firmware
  sets it HIGH/LOW on the `cntl3mot` 0↔nonzero transition (see
  `STM32/CLAUDE.md`'s Motor Control & Trigger Pin section) — including a
  same-day bug/fix where a leftover SW1-button test block was fighting
  the real write every main-loop iteration, found by reading `main.c`
  after the LIN log ruled out an extra command and a multimeter
  confirmed the pin itself was electrically flat during a real run. A
  20s capture on the real Logic Pro 16
  (`saleae/exports/step_response_trigger_test4/`) shows a clean,
  single, ~7.8s-long HIGH pulse aligned with the actual
  `capture_step_response.py` step window.
- **`DigitalTriggerCaptureMode` with a plain `rising` trigger is
  unreliable — false-fires on electrical noise (found 2026-08-18).**
  First real attempt (`saleae/exports/trigger_mode_test1/`) fired
  within seconds of arming, with no motor run at all: the capture shows
  ~1.2ms of chatter across all Hall channels around t=0 and nothing
  else in the whole 10s window, channel 3 never reaching a stable HIGH.
  Same ~100ns commutation-EMI spikes as `analysis/CLAUDE.md`'s
  Hall-Edge RPM Conversion section — a single spike crosses a plain
  rising-edge trigger's threshold, since the hardware trigger has no
  debounce (unlike the software debounce used for Hall-edge analysis).
  **`pulse_high` + `min_pulse_width_seconds` does *not* fix this —
  confirmed broken the same day.** It was the natural fix (filter by
  minimum HIGH duration, well above the noise floor and below the real
  ~7.8s pulse) and `saleae_mcp/server.py`'s `start_capture()` gained the
  parameters for it, but `pulse_high` never fires at all via this API —
  tested against both the real Logic Pro 16 and the `F4241` simulation
  device, with and without a width filter, waited 15s each with no
  trigger. `rising` fires correctly on the same simulation device in
  ~1s, so this is specific to `pulse_high`/`pulse_low`, not a general
  API problem — looks like a `logic2-automation` library issue, not
  fixable from this project's side.
  **Actual fix: stay on `rising`, classify after the fact.**
  `analysis/hall_rpm.py`'s `has_sustained_high()` (added 2026-08-18)
  checks the exported capture for a multi-second HIGH segment on the
  trigger channel (genuine event) vs. only sub-microsecond blips
  (noise); `.claude/skills/saleae-trigger-capture/SKILL.md` retries
  (arm + run + classify, up to 3x) on a false trigger instead of
  treating the first result as final.
- **Confirmed end to end against real hardware (2026-08-18).** First
  full `saleae-trigger-capture` skill run: 1 attempt, no false trigger,
  `has_sustained_high()` correctly classified it `GENUINE`. A second
  attempt earlier the same session correctly classified a real
  `GENUINE`-but-stalled run too — the trigger pin went high right on
  the `cntl3mot` write regardless of whether the motor physically
  turned, which is exactly what the classifier is supposed to detect
  (it answers "did the trigger pin hold high", not "did the motor
  spin" — the watchdog's own stall-check is what caught that
  separately, see `raspi/watchdog/CLAUDE.md`). Once the motor actually
  ran, Hall-vs-LIN rpm agreed closely across ramp-up/steady-state/
  coast-down (`runs/2026-08-18_trigger_capture/
  trigger_capture_hall_vs_lin_rpm.png`), same as every earlier
  `timed`-mode confirmation — and with **zero voice coordination**: no
  "Motor jetzt starten!" needed, the Saleae caught the run on its own.
- Sample rate for the Hall channels — needs to resolve commutation edge
  timing at max RPM without producing unmanageable capture sizes.
- Headless mode (`Manager.launch()` instead of `Manager.connect()`) —
  discussed as a real next step once the headful flow is trusted, not
  built.

Fill these in here once fixed, not in the root `CLAUDE.md`.
