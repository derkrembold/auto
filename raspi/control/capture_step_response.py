"""Step-response capture: speed 0 -> speed <target>, sampling `rpm` at a
fixed interval for a fixed duration, plus `current` at a slower interval.
Real hardware, not a pytest test case — see raspi/CLAUDE.md's Test Suite
Policy. Falls under Motor Execution Consent like any other motor
command, whether run manually on the Pi or triggered remotely.

Prints CSV (elapsed_ms,rpm,current_val1,current_val2) to stdout, one row
per rpm sample. current_val1/val2 are only filled in once every
CURRENT_SAMPLE_INTERVAL (default 1.0s) -- the current sensor's own
on-board averaging window is ~1s (see currentsensor/CLAUDE.md's
countmax/OCR1A tuning), so sampling it faster than that would just
re-read the same averaged value repeatedly. Does not write a CSV file
itself — the caller decides where the data ends up (e.g. saved into
runs/ in the main repo).

Separately, every command sent and reply received is also logged (with
timestamps) to capture_step_response.log (rotated, one generation kept,
see logsetup.rotate_log()) — file only, not echoed to the terminal,
since stdout is reserved for the CSV stream above. See
raspi/watchdog/CLAUDE.md's log-format notes.

Optional --motor/--current-instance (added 2026-09-11, multi-instance
addressing -- see raspi/watchdog/CLAUDE.md's "Multi-Instance Addressing"
section): both default 0. Every watchdog command is now instance-
mandatory, so `motor` is threaded through every speed/pulse/burst/pi/
hal/rpm/status/reset send (including every recovery-sequence strategy);
`current_instance` only affects the `current` reads (a different device
class, its own 0-1 range, independent of which motor is being tested).

Optional --p-delta/--i-delta (added 2026-08-19): if given, sends
`pi <p_delta> <i_delta>` as the very first command, before `speed 0` —
so an out-of-range value (rejected by the watchdog's own validate(),
see watchdog.py's PI_DELTA_MIN/MAX) aborts before the motor moves at
all, not partway through. Range is intentionally NOT re-checked here —
the watchdog is the single source of truth for that, see
run_experiment.py's own docstring for why duplicating it client-side
was deliberately avoided. Omit both to leave KP/KI at their firmware
defaults, same as never calling `pi` at all.

Ends with a staged soft stop (added 2026-08-20), not a single abrupt
`speed 0` — see _soft_stop()'s own docstring for why. Runs after the
sampling loop closes, so it has no effect on the printed CSV/any
ISE-style scoring computed from it.

Optional --target-speed (added 2026-08-27, prompted by kick-starts
being observed at target speeds other than the 1000 default): the step
target, positive or negative (negative = CCW, same sign convention as
`speed`). Defaults to TARGET_SPEED (1000) if omitted, same as before
this flag existed. _soft_stop()'s ramp already scales proportionally
with whatever target_speed it's given, so it needs no change for this.
**Not yet re-validated: DURATION's (7.0s) margin over the settling time
was only ever confirmed at the 1000 default** — see root CLAUDE.md's
Grid Search section ("Future risk, not yet a problem" note) — a
different target speed's settling dynamics aren't guaranteed to fit in
the same window, so treat any run at a non-default --target-speed as
unvalidated on that front until checked against its own capture.

Sends `reset` then `hal` as the very first two commands (added
2026-09-09, prompted by a real stall right after a successful run
leaving `sysError` latched into the next test) — logged only, not
printed to stdout. The leading `reset` gives every run a clean
firmware baseline (no inherited stale `sysError`/counters); the `hal`
read records the rotor's starting position, so a stall/stiction event
can be correlated with exactly where it started (e.g. a known-bad
Mittelrast, see `STM32/CLAUDE.md`'s Hall-chattering finding).

**The soft-stop ramp is now conditional (added 2026-09-09).** After the
sampling loop, `hal`/`rpm`/`status` are read again (also logged only)
and used to decide whether the motor actually got moving:
`_soft_stop()` only runs if `rpm` reached at least
`STOP_RAMP_RPM_FRACTION` (0.5) of `target_speed` *and* `status`'s
`sys_error` isn't `STALL_TIM_ERR`. Otherwise a plain `speed 0` is sent
instead. Found live: on a genuinely stuck rotor (e.g. parked in a
Mittelrast), `_soft_stop()`'s own descending nonzero `speed` commands
re-arm `controlvariableinput` and restart the whole firmware
stuck-detection sequence from scratch — confirmed via `status`'s
`kickstart` counter reading 6 instead of the 3 the stuck-window range
alone explains, the extra 3 having fired *during* the ramp. See
`STM32/CLAUDE.md`'s Status section for what each `sysError` value
means.

**Mid-run stall detection + one recovery attempt (added 2026-09-09),
built after `burst` was confirmed (twice) to reliably escape a real,
reproducible Mittelrast stall (Hall state 2/`010`, between states 2 and
3 -- see `STM32/CLAUDE.md`).** Design discussed and agreed with the
user step by step before writing any of it:
- `STALL_CHECK_DELAY_S` (1.0s) into the step, if `rpm` is still 0, read
  `status` to confirm: only a *latched* `STALL_TIM_ERR` counts as a
  real stall (matches the firmware's own give-up point, ~700ms in --
  comfortably before the 1.0s check). A transient `rpm=0` alone isn't
  trusted, same reasoning as the soft-stop decision above.
- On a confirmed stall: a random *recovery sequence* runs (see
  `STRATEGIES`/`_generate_recovery_sequence()` below), then the
  **entire step is retried from scratch** (`reset`, `hal`, `speed 0`,
  `speed <target>`, fresh sampling) -- this retry's rpm trajectory is
  the raw evidence of whether the sequence worked, *not* a
  script-computed success/fail label (that call is left to the
  analysis tool -- see the recovery-log section below).
- If the retry also confirms a stall: **stop -- no second recovery
  sequence, no third attempt.** The run aborts (`sys.exit()`) since
  there's no usable capture to report; the recovery-log rows are
  written first.
- If the retry doesn't re-stall: *that* attempt's rows (not the failed
  first attempt's) become the CSV printed to stdout -- callers
  (`run_grid.py` etc.) see one normal, clean step response either way,
  never a truncated stalled one.

**Recovery sequence design (`STRATEGIES`, `_generate_recovery_sequence()`),
also agreed step by step, not guessed:**
- A fixed, hand-picked catalog, not continuously-random parameters --
  every value has already been real-hardware-tested (`burst_cw` is the
  exact `-500 10 1000 5` combo confirmed twice against the Mittelrast
  above; `burst_ccw` is its direction-mirrored counterpart, values
  sign-flipped, untested but symmetric). `speed_max_plus`/
  `speed_max_minus` (±1000) added 2026-09-10: from the 010/110
  Mittelrast a `speed 1000` start usually breaks free where `speed 500`
  does not (more duty/current/torque against the dead-zone).
- 2-3 strategies per sequence (`SEQUENCE_MIN/MAX_LEN`) -- long enough
  to combine building blocks, short enough to stay analyzable (which
  step mattered) and to bound total motor/electronics stress.
- At most 1 `burst`, 2 `pulse`, and 1 full-speed (`speed_max_plus` and
  `speed_max_minus` COMBINED -- `SEQUENCE_MAX_FULLSPEED`,
  `FULLSPEED_STRATEGIES`) total per sequence (not just non-adjacent --
  straight count caps), and never the same strategy twice in a row --
  all explicitly to avoid repeating the kind of rapid multi-pulse /
  full-power-reversal stress implicated in the 2026-09-08 MOSFET
  failure (see `STM32/CLAUDE.md`'s Known Hardware Issue section).
- At least `SEQUENCE_STEP_PAUSE_S` (0.1s) between every step regardless
  of kind, for the same electronics-stress reason. A `speed` strategy
  additionally holds for `SPEED_STRATEGY_HOLD_S` (0.5s -- deliberately
  under the firmware's own `STALL_TIM_ERR` give-up point, ~700ms, so a
  `speed` step itself never latches a stall) then sends `speed 0`
  before the inter-step pause, so a `pulse`/`burst` step never follows
  a still-active nonzero closed-loop command. The full-speed strategies
  use this same 0.5s hold: the firmware zeroes its drive at the ~700ms
  give-up anyway, so a longer hold would add the stall flag without
  adding hard-drive time. If real `recovery_sequences.csv` data later
  shows 0.5s of `speed ±1000` doesn't clear the 010/110 Mittelrast,
  revisit -- with data, not a guess.

Every recovery attempt is appended to `RECOVERY_LOG_PATH`
(`recovery_sequences.csv`) as **two rows** (schema reworked 2026-09-10,
step by step with the user), both plain appends, joined by `timestamp`
(microsecond precision -- a unique key):
  - phase `"sequence"`: `hal_before_sequence`/`status_before_sequence`
    (state the sequence started from) + `sequence` (the *exact commands
    sent*, e.g. `"speed 500;speed 0;burst 500 10 -1000 5"`, not the
    abstract `STRATEGIES` keys -- the catalog's values may change
    later) + `hal_after_sequence`/`status_after_sequence` (what the
    sequence did). Written right after the sequence completes -- a
    self-contained "sequence X, from state Y to state Z" training
    example on its own.
  - phase `"retry"`: `rpm_1s` / `rpm_1p5s` -- the retry's rpm at ~1.0s
    and ~1.5s in -- plus `status_after_retry`, the full `status` reply
    read once right after the retry's sampling ends (added 2026-09-10).
    Raw values, *no success/fail label* -- the analysis tool picks the
    threshold, and can re-pick it later without old rows being stuck at
    today's definition. `status_after_retry` exists to catch a real
    2026-09-10 case: a retry logged `rpm_1s`/`rpm_1p5s` = 475 with the
    motor visibly not turning -- spurious Hall-chatter edges (see
    `STM32/CLAUDE.md`) counting as movement. A latched `STALL_TIM_ERR`
    in `status_after_retry` despite a nonzero `rpm_1s`/`rpm_1p5s` is
    the tell that the "recovery" didn't actually recover anything.
A `"sequence"` row with no matching `"retry"` row means the retry broke
or was interrupted before measurement -- that absence is itself a
signal, not a hole. Deliberately a separate, never-rotated file from
`LOG_PATH` above, meant to keep growing forever as training data for
the planned learning/decision-tree work.
"""
import argparse
import csv
import datetime
import logging
import os
import random
import re
import sys
import time
from multiprocessing.connection import Client

import logsetup
from motorcontrol import SOCKET_ADDRESS

LOG_PATH = "capture_step_response.log"
logger = logging.getLogger("capture_step_response")

# Append-only record of every recovery sequence (added 2026-09-09,
# schema reworked 2026-09-10) -- deliberately separate from LOG_PATH
# above, which rotates (one generation kept, see logsetup.rotate_log())
# and would lose sequence history after just two runs. This file is
# never rotated or truncated -- it keeps growing forever, as training
# data for the planned learning/decision-tree analysis (see
# raspi/watchdog/CLAUDE.md's "Planned Logging Database" section -- this
# is a small, single-motor-bench-scoped precursor to that).
#
# Two rows per recovery attempt, both plain appends, joined by
# `timestamp` (microsecond precision -- a guaranteed-unique key, two
# attempts can't share a microsecond):
#  - phase "sequence": written right after the sequence runs and its
#    after-state is read -- the complete "sequence X, from state Y to
#    state Z" record, a usable training example on its own.
#  - phase "retry": written after the retry's rpm measurement -- did the
#    motor actually run afterward (rpm_1s / rpm_1p5s, raw, no
#    success/fail label -- the analysis tool decides the threshold),
#    plus status_after_retry: the full `status` reply just after the
#    retry sampling ends. A latched STALL_TIM_ERR there despite a
#    nonzero rpm means spurious Hall-chatter edges, not real rotation
#    (see the module docstring / STM32/CLAUDE.md).
# A "sequence" row with no matching "retry" row = the retry broke or
# was interrupted before measurement. That absence is itself a signal.
RECOVERY_LOG_PATH = "recovery_sequences.csv"
RECOVERY_LOG_FIELDS = [
    "timestamp", "phase", "target_speed",
    "hal_before_sequence", "status_before_sequence", "sequence",
    "hal_after_sequence", "status_after_sequence",
    "rpm_1s", "rpm_1p5s", "status_after_retry",
]

TARGET_SPEED = 1000
SAMPLE_INTERVAL = 0.2  # seconds, rpm sampling
CURRENT_SAMPLE_INTERVAL = 1.0  # seconds -- matches the current sensor's own averaging window
DURATION = 7.0  # seconds, measured from the speed step, not from speed 0

STOP_RAMP_STEPS = 5  # number of speed commands sent during the soft stop, last one is always 0
STOP_RAMP_DURATION = 1.0  # seconds, total time from the first reduced speed to the final 0
STOP_RAMP_RPM_FRACTION = 0.5  # only soft-stop if rpm reached at least this fraction of target_speed

# Mirrors STM32/firmware/Core/Inc/errors.h's STALL_TIM_ERR -- not
# generated/shared automatically (see addresses.json's Python/firmware
# generation for PIDs, which this doesn't have an equivalent of for
# error codes), so keep this in sync by hand if errors.h ever changes.
STALL_TIM_ERR = -65

RPM_RE = re.compile(r"rpm=(-?\d+)")
CURRENT_RE = re.compile(r"val1=(\S+) val2=(\S+)")
SYS_ERROR_RE = re.compile(r"sys_error=(-?\d+)")

# --- mid-run stall recovery (added 2026-09-09, see the module docstring
# for the full design discussion) ---

STALL_CHECK_DELAY_S = 1.0  # how far into a step to check for a stall (also the rpm_1s capture point)
RPM_SAMPLE_2_S = 1.5  # second rpm capture point into the retry, for recovery_sequences.csv

SEQUENCE_MIN_LEN = 2
SEQUENCE_MAX_LEN = 3
SEQUENCE_STEP_PAUSE_S = 0.1  # minimum pause between any two sequence steps
SPEED_STRATEGY_HOLD_S = 0.5  # how long any "speed" strategy holds before its speed-0 cleanup
SEQUENCE_MAX_BURST = 1  # per sequence, total, not just non-adjacent
SEQUENCE_MAX_PULSE = 2  # per sequence, total
SEQUENCE_MAX_FULLSPEED = 1  # speed_max_plus + speed_max_minus COMBINED, per sequence, total

# The two full-speed (|value| == TARGET_SPEED) "speed" strategies. Added
# 2026-09-10 after a real observation: from the reproducible 010/110
# Mittelrast, a `speed 1000` start usually breaks the rotor free where
# `speed 500` does not -- higher commanded speed means more duty/current/
# torque against the cogging/dead-zone. Capped hard at SEQUENCE_MAX_
# FULLSPEED per sequence (forward-then-reverse at full power is the shape
# closest to the 2026-09-08 MOSFET failure -- see STM32/CLAUDE.md's Known
# Hardware Issue). Same 0.5s SPEED_STRATEGY_HOLD_S as the ±500 ones:
# still under the firmware's ~700ms STALL_TIM_ERR give-up, so the
# strategy never latches a stall itself; the useful hard-drive window
# ends at that give-up anyway (the firmware zeroes controlvariableinput/
# integral there), so a longer hold would add the stall flag without
# adding drive time.
FULLSPEED_STRATEGIES = ("speed_max_plus", "speed_max_minus")

# Fixed, hand-picked catalog -- every value already real-hardware-tested
# (see module docstring), not continuously-random parameters.
STRATEGIES = {
    "speed0": {"kind": "speed", "value": 0},
    "speed_plus": {"kind": "speed", "value": 500},
    "speed_minus": {"kind": "speed", "value": -500},
    "speed_max_plus": {"kind": "speed", "value": 1000},
    "speed_max_minus": {"kind": "speed", "value": -1000},
    "pulse_plus": {"kind": "pulse", "value": 1000},
    "pulse_minus": {"kind": "pulse", "value": -1000},
    "burst_cw": {"kind": "burst", "value1": -500, "pause1_ms": 10, "value2": 1000, "pause2_ms": 5},
    "burst_ccw": {"kind": "burst", "value1": 500, "pause1_ms": 10, "value2": -1000, "pause2_ms": 5},
}


def _send(conn, command):
    logger.info(f"-> {command}")
    conn.send(command)
    reply = conn.recv()
    logger.info(f"<- {reply}")
    return reply


def _read_rpm(conn, motor):
    match = RPM_RE.search(_send(conn, f"rpm {motor}"))
    return int(match.group(1)) if match else None


def _read_current(conn, current_instance):
    match = CURRENT_RE.search(_send(conn, f"current {current_instance}"))
    return (match.group(1), match.group(2)) if match else (None, None)


def _generate_recovery_sequence(rng=random):
    # Retries whole-sequence generation on a dead end (e.g. the last
    # slot has no valid candidate left) rather than backtracking --
    # simple, and dead ends are rare with this small a catalog/length.
    length = rng.randint(SEQUENCE_MIN_LEN, SEQUENCE_MAX_LEN)
    names = list(STRATEGIES.keys())
    while True:
        sequence = []
        burst_count = 0
        pulse_count = 0
        fullspeed_count = 0
        for _ in range(length):
            candidates = names[:]
            rng.shuffle(candidates)
            picked = None
            for name in candidates:
                kind = STRATEGIES[name]["kind"]
                if sequence and name == sequence[-1]:
                    continue
                if kind == "burst" and burst_count >= SEQUENCE_MAX_BURST:
                    continue
                if kind == "pulse" and pulse_count >= SEQUENCE_MAX_PULSE:
                    continue
                if name in FULLSPEED_STRATEGIES and fullspeed_count >= SEQUENCE_MAX_FULLSPEED:
                    continue
                picked = name
                break
            if picked is None:
                break  # dead end -- restart the whole sequence
            sequence.append(picked)
            if STRATEGIES[picked]["kind"] == "burst":
                burst_count += 1
            elif STRATEGIES[picked]["kind"] == "pulse":
                pulse_count += 1
            if picked in FULLSPEED_STRATEGIES:
                fullspeed_count += 1
        if len(sequence) == length:
            return sequence


def _execute_strategy(conn, name, motor):
    # Returns the exact command(s) sent (not just `name`) -- the
    # catalog's own parameter values could change later (2026-09-09,
    # explicit user request), so the log needs to capture what was
    # actually tried, not a label whose meaning could drift over time.
    # Every command includes `motor` (2026-09-11, multi-instance
    # addressing) -- which motor the sequence targeted is now visible
    # directly in the logged command text, no separate field needed.
    strategy = STRATEGIES[name]
    kind = strategy["kind"]
    commands = []
    if kind == "speed":
        cmd = f"speed {motor} {strategy['value']}"
        _send(conn, cmd)
        commands.append(cmd)
        if strategy["value"] != 0:
            time.sleep(SPEED_STRATEGY_HOLD_S)
            stop_cmd = f"speed {motor} 0"
            _send(conn, stop_cmd)
            commands.append(stop_cmd)
    elif kind == "pulse":
        cmd = f"pulse {motor} {strategy['value']}"
        _send(conn, cmd)
        commands.append(cmd)
    elif kind == "burst":
        cmd = (f"burst {motor} {strategy['value1']} {strategy['pause1_ms']} "
               f"{strategy['value2']} {strategy['pause2_ms']}")
        _send(conn, cmd)
        commands.append(cmd)
    time.sleep(SEQUENCE_STEP_PAUSE_S)
    return commands


def _run_recovery_sequence(conn, motor):
    sequence = _generate_recovery_sequence()
    logger.info(f"stall confirmed -- running recovery sequence: {sequence}")
    commands = []
    for name in sequence:
        commands.extend(_execute_strategy(conn, name, motor))
    return commands


def _append_recovery_row(row):
    # One plain append -- writes the header first only if the file is
    # new, never truncates an existing one. `row` is a dict of any
    # subset of RECOVERY_LOG_FIELDS; missing fields are written blank.
    # See RECOVERY_LOG_PATH's own comment for the two-phase layout.
    file_is_new = not os.path.exists(RECOVERY_LOG_PATH)
    with open(RECOVERY_LOG_PATH, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RECOVERY_LOG_FIELDS)
        if file_is_new:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in RECOVERY_LOG_FIELDS})


def _run_one_attempt(conn, motor, current_instance, target_speed, sample_interval,
                      current_sample_interval, duration):
    # One full step attempt: speed 0 -> speed <target> -> sample until
    # `duration` or until a stall is confirmed (see module docstring).
    # Returns (rows, stalled, rpm_1s, rpm_1p5s). rpm_1s / rpm_1p5s are
    # the first rpm sample at/after STALL_CHECK_DELAY_S / RPM_SAMPLE_2_S
    # (None if `duration` is too short to reach them) -- only the retry
    # call's values get logged, attempt 1 ignores them. On a confirmed
    # stall, sampling still runs long enough to capture rpm_1p5s, then
    # stops early -- no point sampling the full window for a hopeless
    # retry, but both rpm data points must exist for the log.
    _send(conn, f"speed {motor} 0")
    _send(conn, f"speed {motor} {target_speed}")
    start = time.monotonic()
    next_current_sample = start
    stall_checked = False
    stalled = False
    rpm_1s = None
    rpm_1p5s = None

    rows = []
    sample_count = int(duration / sample_interval)
    for i in range(sample_count):
        # Scheduled against the absolute start time, not accumulated
        # sleeps, so LIN round-trip latency for each rpm read doesn't
        # drift the sample interval over the run.
        target_time = start + i * sample_interval
        now = time.monotonic()
        if target_time > now:
            time.sleep(target_time - now)
        rpm = _read_rpm(conn, motor)

        current_val1 = current_val2 = ""
        if time.monotonic() >= next_current_sample:
            current_val1, current_val2 = _read_current(conn, current_instance)
            next_current_sample += current_sample_interval

        elapsed_ms = (time.monotonic() - start) * 1000
        rows.append((elapsed_ms, rpm, current_val1, current_val2))

        if not stall_checked and elapsed_ms >= STALL_CHECK_DELAY_S * 1000:
            stall_checked = True
            rpm_1s = rpm
            if rpm == 0:
                status_reply = _send(conn, f"status {motor}")
                sys_error_match = SYS_ERROR_RE.search(status_reply)
                sys_error = int(sys_error_match.group(1)) if sys_error_match else None
                stalled = sys_error == STALL_TIM_ERR

        if rpm_1p5s is None and elapsed_ms >= RPM_SAMPLE_2_S * 1000:
            rpm_1p5s = rpm
            if stalled:
                return rows, True, rpm_1s, rpm_1p5s

    return rows, stalled, rpm_1s, rpm_1p5s


def _soft_stop(conn, motor, target_speed, steps=STOP_RAMP_STEPS, duration=STOP_RAMP_DURATION):
    # A single abrupt `speed 0` after a sustained high speed was
    # observed live (2026-08-20) to stop the motor harder than a plain
    # coast-down would -- plausibly the PI controller reacting to a
    # sudden large negative error rather than the rotor just freewheeling
    # down under friction. Firmware's own updateramp() stays disabled
    # (updateramp(false), see STM32/CLAUDE.md's Commutation & Control
    # section) deliberately -- re-enabling it would also smooth the
    # *start* of the step, undoing the whole point of turning it off.
    # This ramps down in stages from the Python side instead, only
    # affecting the stop.
    step_interval = duration / (steps - 1)
    for i in range(steps - 1, 0, -1):
        _send(conn, f"speed {motor} {round(target_speed * i / steps)}")
        time.sleep(step_interval)
    _send(conn, f"speed {motor} 0")


def run(address=SOCKET_ADDRESS, target_speed=TARGET_SPEED,
        sample_interval=SAMPLE_INTERVAL,
        current_sample_interval=CURRENT_SAMPLE_INTERVAL, duration=DURATION,
        p_delta=None, i_delta=None, motor=0, current_instance=0):
    logsetup.configure("capture_step_response", LOG_PATH, terminal_level=None)

    # One persistent connection for the whole run — see
    # validate_speed.py's same choice for why (one-shot connections
    # trigger the watchdog's stop-on-disconnect after every command).
    with Client(address, family='AF_UNIX') as conn:
        # Clean firmware state before this run -- clears
        # controlvariableinput/integral/counters/sysError (see
        # linbus.reset_motor()'s docstring), so this run doesn't inherit
        # a latched sysError or a stale kickstart/counter baseline from
        # whatever happened before. Also makes the "status" read at the
        # end below an exact before/after delta for *this* run, not an
        # ambiguous whole-session total.
        _send(conn, f"reset {motor}")
        # Starting Hall position (2026-09-09) -- logged only, lets a
        # stall/stiction event found later be correlated with exactly
        # where the rotor started (e.g. a known-bad Mittelrast, see
        # STM32/CLAUDE.md's Hall-chattering finding), not just guessed
        # at after the fact.
        _send(conn, f"hal {motor}")
        if p_delta is not None or i_delta is not None:
            reply = _send(conn, f"pi {motor} {p_delta} {i_delta}")
            if not reply.startswith("OK"):
                sys.exit(f"pi command rejected, aborting before touching the motor: {reply}")

        rows, stalled, _, _ = _run_one_attempt(conn, motor, current_instance, target_speed,
                                                sample_interval, current_sample_interval, duration)

        if stalled:
            # phase "sequence": everything about what state the sequence
            # started from and what it did -- read the before-state, run
            # the sequence, read the after-state, then append one row.
            # The retry's rpm result is phase "retry" below, joined on
            # the same timestamp. See RECOVERY_LOG_PATH's comment.
            seq_timestamp = datetime.datetime.now().isoformat()
            hal_before = _send(conn, f"hal {motor}")
            status_before = _send(conn, f"status {motor}")
            sequence = _run_recovery_sequence(conn, motor)
            hal_after = _send(conn, f"hal {motor}")
            status_after = _send(conn, f"status {motor}")
            _append_recovery_row({
                "timestamp": seq_timestamp,
                "phase": "sequence",
                "target_speed": target_speed,
                "hal_before_sequence": hal_before,
                "status_before_sequence": status_before,
                "sequence": ";".join(sequence),
                "hal_after_sequence": hal_after,
                "status_after_sequence": status_after,
            })

            _send(conn, f"reset {motor}")
            _send(conn, f"hal {motor}")
            rows, stalled_again, rpm_1s, rpm_1p5s = _run_one_attempt(
                conn, motor, current_instance, target_speed, sample_interval,
                current_sample_interval, duration)
            # Full `status` reply once, right after the retry's sampling
            # ends (2026-09-10). Catches the case where the retry's `rpm`
            # reads nonzero on a rotor that never actually turned --
            # spurious Hall-chatter edges accumulating in hallCounter
            # while stationary (see STM32/CLAUDE.md's Hall-chattering
            # finding; a real 2026-09-10 recovery retry logged rpm_1s /
            # rpm_1p5s = 475 with the motor visibly still). A latched
            # STALL_TIM_ERR in this field despite a nonzero rpm_1s /
            # rpm_1p5s is the tell the analysis tool needs -- raw reply,
            # no script-side interpretation, same reasoning as the raw
            # rpm values.
            status_after_retry = _send(conn, f"status {motor}")
            _append_recovery_row({
                "timestamp": seq_timestamp,
                "phase": "retry",
                "rpm_1s": "" if rpm_1s is None else rpm_1s,
                "rpm_1p5s": "" if rpm_1p5s is None else rpm_1p5s,
                "status_after_retry": status_after_retry,
            })
            if stalled_again:
                logger.info(f"recovery sequence did not recover: {sequence} "
                            f"(rpm_1s={rpm_1s} rpm_1p5s={rpm_1p5s})")
                sys.exit(f"stall persisted after recovery sequence {sequence} "
                         "-- giving up, no usable capture")
            logger.info(f"recovery sequence recovered: {sequence} "
                        f"(rpm_1s={rpm_1s} rpm_1p5s={rpm_1p5s})")

        print("elapsed_ms,rpm,current_val1,current_val2")
        for elapsed_ms, rpm, current_val1, current_val2 in rows:
            print(f"{elapsed_ms:.0f},{rpm},{current_val1},{current_val2}")

        # Decision point (2026-09-09): only run the soft-stop ramp if
        # the motor actually got moving -- otherwise the ramp's own
        # nonzero speed commands re-arm controlvariableinput and
        # restart the whole stuck-detection sequence on a rotor that
        # was never moving in the first place. Found live: a Mittelrast
        # stall's "status" showed kickstart=6, not the 3 the stuck
        # window range alone explains -- the extra 3 fired *during* the
        # soft-stop ramp itself. Two independent "didn't really move"
        # signals, either one is enough to skip: rpm well below target
        # (not just nonzero -- a single Hall-count blip, like the
        # rpm=25 seen during that same stall, isn't real movement
        # either) and/or sysError already showing STALL_TIM_ERR (the
        # firmware's own, more reliable confirmation that it gave up).
        _send(conn, f"hal {motor}")
        rpm = _read_rpm(conn, motor)
        status_reply = _send(conn, f"status {motor}")
        sys_error_match = SYS_ERROR_RE.search(status_reply)
        sys_error = int(sys_error_match.group(1)) if sys_error_match else None

        moved_enough = rpm is not None and abs(rpm) >= STOP_RAMP_RPM_FRACTION * abs(target_speed)
        no_stall_latched = sys_error is not None and sys_error != STALL_TIM_ERR
        if moved_enough and no_stall_latched:
            _soft_stop(conn, motor, target_speed)
        else:
            logger.info(f"skipping soft-stop ramp -- rpm={rpm} sys_error={sys_error} "
                        f"target_speed={target_speed}")
            _send(conn, f"speed {motor} 0")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--p-delta", type=float, default=None)
    parser.add_argument("--i-delta", type=float, default=None)
    parser.add_argument("--target-speed", type=int, default=TARGET_SPEED,
                         help=f"step target, +/- (default {TARGET_SPEED})")
    parser.add_argument("--motor", type=int, default=0,
                         help="motor instance to drive/read, 0-3 (default 0)")
    parser.add_argument("--current-instance", type=int, default=0,
                         help="currentsensor instance to read, 0-1 (default 0)")
    args = parser.parse_args()
    if (args.p_delta is None) != (args.i_delta is None):
        sys.exit("--p-delta and --i-delta must be given together, or not at all")
    run(p_delta=args.p_delta, i_delta=args.i_delta, target_speed=args.target_speed,
        motor=args.motor, current_instance=args.current_instance)
