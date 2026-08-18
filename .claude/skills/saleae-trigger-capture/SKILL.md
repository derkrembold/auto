---
name: saleae-trigger-capture
description: Run a Saleae hardware-trigger-mode capture end-to-end — physical pre-flight checklist, one consent for the motor run, then arm the Saleae, run capture_step_response.py on the Pi, export the capture, and produce the Hall-vs-LIN rpm overlay plot. No further prompts once confirmed. Use when the user wants to test or use the Saleae trigger pin for a real capture (as opposed to a manually-timed capture coordinated by voice).
---

Built 2026-08-18 to replace the voice-coordinated "Motor jetzt
starten!" workflow used for earlier `timed`-mode captures — the whole
point of the hardware trigger pin (`STM32/CLAUDE.md`'s Motor Control &
Trigger Pin section) is that the Saleae catches the motor run on its
own, so this skill only needs one consent point instead of a live
back-and-forth.

## 1. Show the physical pre-flight checklist (no consent needed)

Print `saleae/CLAUDE.md`'s Physical Pre-Flight Checklist section
verbatim (STM32 running, Logic 2 + automation server, Saleae USB, motor
power/battery on, wiring, watchdog `--live`) and wait for the user to
confirm it's done. Purely informational — none of this is
Claude-checkable except the STM32/watchdog state, which the read-only
check below covers.

```
ssh pi@motorpi.local "pgrep -af watchdog.py; echo '---'; tail -3 /home/pi/auto/watchdog.log" 2>&1
```

If the watchdog isn't running `--live`, or the STM32 isn't answering
(no recent `ret=0` lines), say so and stop here — don't proceed to the
consent question with a setup that can't actually work.

## 2. One consent question, then no further prompts

Ask: **"Soll ich das Experiment jetzt starten?"** This is the Motor
Execution Consent moment (`raspi/CLAUDE.md`'s Motor Execution Consent
section — `capture_step_response.py` issues real `speed` commands) —
explicit, in-the-moment, every invocation, no exceptions. Once the user
confirms, run steps 3-6 straight through without asking again.

**If step 1's checklist confirmation is more than ~2 minutes old when
this question is actually asked** (a debugging detour ate the time
between showing the checklist and reaching this point — hit live
2026-08-18, a `pulse_high` investigation ran ~20+ minutes between
checklist and consent, motor power had gone off in the meantime and the
run stalled), re-show at least the motor power/battery line from the
checklist as part of this question rather than silently trusting the
earlier confirmation — physically-unverifiable state (unlike
STM32/watchdog, which the step-1 SSH check actually confirms) can go
stale exactly like consent itself does.

## 3-4. Arm + run, in a retry loop (up to 3 attempts)

**Use `trigger_type="rising"`, not `pulse_high`.** `pulse_high` +
`min_pulse_width_seconds` was built 2026-08-18 specifically to filter
this project's trigger pin's ~100ns EMI spikes (see
`analysis/CLAUDE.md`'s Hall-Edge RPM Conversion section) out of a
plain rising-edge trigger — but confirmed broken the same day against
both the real Logic Pro 16 and the simulation device: it never fires at
all (tested with and without a width filter, waited 15s each). Root
cause looks like a `logic2-automation` library issue, not anything in
this project's code. Use `rising` and handle false triggers in
software instead (below).

**Always use `wait_for_capture_or_timeout()`, never bare
`wait_for_capture()`.** An abandoned wait (killed process, tool
timeout) leaves the capture running on the Logic 2 side with nothing
left to call `stop_capture()` on it — Logic 2 gets stuck "recording"
and every subsequent `start_capture()` fails with
`InternalServerError: Cannot switch sessions while recording` until
someone clicks Stop by hand in the GUI. Hit live 2026-08-18, twice, on
exactly this mistake. `wait_for_capture_or_timeout(capture_id,
timeout_seconds)` (added to `saleae_mcp/server.py` the same day) calls
`stop_capture()` internally on timeout so this can't happen.

MCP tools aren't natively callable this session unless already
approved (see `saleae/CLAUDE.md`'s MCP Server section) — invoke
`saleae_mcp/server.py`'s functions directly via a backgrounded Python
script instead, same pattern as every real capture so far this
project. Loop the arm+run+check below up to 3 times, since a `rising`
trigger can still false-fire on noise before the real motor edge ever
arrives (in which case the capture completes on garbage before
`capture_step_response.py` even runs) — `analysis/hall_rpm.py`'s
`has_sustained_high()` tells genuine from false after the fact by
checking for a multi-second HIGH segment on the trigger channel (a real
event) vs only sub-microsecond blips (noise):

```python
import sys
sys.path.insert(0, r"C:\Users\rembo\Documents\Auto\saleae_mcp")
sys.path.insert(0, r"C:\Users\rembo\Documents\Auto")
import server
from analysis.hall_rpm import has_sustained_high

DEVICE_ID = "DB59F8F22EA91DEA"  # real Logic Pro 16, see saleae/CLAUDE.md
CHANNELS = [0, 1, 2, 3]         # 0-2 = H1/H2/H3, 3 = trigger pin
SAMPLE_RATE = 10_000_000
export_name = "trigger_capture_<TIMESTAMP>"  # fill in, e.g. 2026-08-18_1130

res = server.start_capture(
    device_id=DEVICE_ID, digital_channels=CHANNELS,
    digital_sample_rate=SAMPLE_RATE, capture_mode="trigger",
    trigger_channel_index=3, trigger_type="rising",
    after_trigger_seconds=10,  # comfortably covers the ~7.8s step window
)
capture_id = res["capture_id"]
print(f"ARMED capture_id={capture_id}", flush=True)
```

Run this with `Bash`, `run_in_background: true`, poll once for `ARMED`,
then **immediately** (minimize the gap — a false trigger firing in this
window means the real edge is missed entirely, the capture already
completed) run the motor test on the Pi:

```
ssh pi@motorpi.local "cd /home/pi/auto && python3 capture_step_response.py" > runs/<date>_trigger_capture/capture_step_response.csv
```

This blocks for ~9s (ramp + ~7.8s hold + stop) and is what actually
raises the trigger pin. Then, in a second script invocation (or the
same process if still alive), wait bounded and classify:

```python
result = server.wait_for_capture_or_timeout(capture_id, timeout_seconds=20)
print(result, flush=True)
export_res = server.export_capture(capture_id, export_name, digital_channels=CHANNELS)
server.save_capture(capture_id, export_name)
server.close_capture(capture_id)

genuine = has_sustained_high(f"{export_res['export_dir']}/digital.csv", min_duration_s=0.5)
print("GENUINE" if genuine else "FALSE_TRIGGER", flush=True)
```

If `FALSE_TRIGGER` (or `status == "timed_out"`): tell the user briefly
("Fehlalarm, versuche nochmal"), discard the export, and retry from the
top of this section with a fresh `export_name`. After 3 failed
attempts, stop and report to the user instead of looping forever.

## 5. Analyze

Once `GENUINE`: run the Hall-vs-LIN overlay, same as
`runs/2026-08-17_trigger_pin_test4/plot_hall_vs_lin_rpm.py` but
simpler — in `trigger` mode the Saleae's capture-relative t=0 **is**
the trigger edge (the `cntl3mot` speed-nonzero write), so there's no
`TRIGGER_HIGH_T` offset to compute: the Hall-derived rpm and the
`capture_step_response.py` CSV's `elapsed_ms` column are already on the
same clock. Use `analysis/hall_rpm.py`'s `hall_rpm_from_csv()` directly
against the exported `digital.csv`.

Save the plot into `runs/<date>_trigger_capture/`, send it with
`SendUserFile`.

## 6. Report

State how many attempts it took (1 is the success case; 2-3 means
false triggers happened but were caught, still a successful run) and
summarize whether the Hall/LIN rpm traces agree, same sanity check as
`analysis/CLAUDE.md`'s Hall-Edge RPM Conversion section describes.
