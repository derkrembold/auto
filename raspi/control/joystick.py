"""Joystick-driven dual-motor control (Issue #19) — Process 1 from
raspi/watchdog/CLAUDE.md's "Planned Multi-Process Architecture" section.
Reads a Logitech Wireless Gamepad F710 (via its proprietary 2.4GHz USB
dongle, not Bluetooth) through pygame, computes a differential-drive
speed pair, and sends it to the watchdog over the same persistent IPC
connection model motorcontrol.py already uses.

Falls under Motor Execution Consent like any other motor-commanding
script (see raspi/CLAUDE.md) whenever run with --live. --simulate is
the DEFAULT (mirrors watchdog.py's own dry-run-by-default/--live
convention, same code-level reinforcement of Motor Execution Consent):
no IPC connection is opened at all, every `speed <instance> <value>`
command that would have been sent is only logged/printed instead.
Pass --live to actually connect to the watchdog and drive real motors
— every time, no assuming a previous run's consent carries over.

**Mutually exclusive with motorcontrol.py, by design** — decided
2026-09-18 (see Issue #19's discussion): the watchdog's own accept
loop only ever services one connected client at a time anyway, and
running two simultaneous command sources against the same motors is
itself hazardous, independent of that implementation detail. Only one
of motorcontrol.py / joystick.py --live is ever running at once.

**Right stick only, left stick unused for now.** Uses the F710's D/X
switch mode this controller currently happens to be in (not explicitly
identified). Axis indices below are this session's best calibrated
read (2026-09-21, via repeated --debug captures) — flagged
UNVERIFIED-BEYOND-THIS-SESSION since earlier, less-controlled captures
in the same session briefly showed a different (self-inconsistent)
mapping, most likely from imprecise by-hand stick isolation rather
than a real driver quirk. Re-confirm with --debug if anything about
the controller/driver/OS changes, and treat the very first slow --live
test as the real confirmation, not just this log reading.

## Differential drive mapping

    vorwaerts = -get_axis(axis_forward)   # stick pushed forward (away from body) -> positive
    lenkung   =  get_axis(axis_steer)
    frac_left  = clamp(vorwaerts + lenkung, -1.0, 1.0)
    frac_right = clamp(vorwaerts - lenkung, -1.0, 1.0)
    speed_left  = round(frac_left  * MAX_RPM) * DIRECTION_SIGN[left_dir]
    speed_right = round(frac_right * MAX_RPM) * DIRECTION_SIGN[right_dir]

Calibrated axis indices (right stick): --axis-forward 4 (away from
body = -1.0 raw, flipped positive above), --axis-steer 3 (sign of
"left" vs "right" not yet independently confirmed -- verify by
watching the vehicle at the first slow --live test). Deadzone (500,
matching lincomm.py's own `abs(value) < 500 -> 0` precedent) is
applied to the final wire-scale speed value, same units lincomm.py
applied it in — not to the raw -1.0..1.0 axis fraction.

**MAX_RPM defaults to 1200, not the 1400 first discussed** — changed
2026-09-18 to match the highest speed actually validated end-to-end on
real hardware so far (validate_speed.py's ramp topped out at 1200,
confirmed 2026-08-04 with rpm tracking speed within ~6%), rather than
running slightly above anything ever tested. Well under the watchdog's
own SPEED_MAX (3000) either way — this is a tool-level driving cap, not
a protocol limit.

**--left-dir/--right-dir (cw/ccw), required, no default.** Which
physical motor ends up left/right, and which sign convention on each
one's wire means "this wheel spins the vehicle forward," isn't
knowable until after physical installation — see Issue #19's design
discussion. Convention: "cw" = no flip, a positive computed
frac_left/frac_right value is sent as-is; "ccw" = flip, the value is
negated before sending. Determining which value is *correct* for a
given motor requires a real, consented low-speed test after
installation (Motor Execution Consent applies same as any other live
run) — these flags don't guess that for you.

## Dead-man confirmation — any input change, not a dedicated button

Redesigned 2026-09-21 from the original periodic-button-repress idea
(see Issue #19's design comment for that earlier version). Settled
through discussion: LT (calibrated as --axis-lt, index 2) turned out
to be an analog axis on this controller, not a digital button — which
prompted reconsidering the mechanism itself rather than bolting on a
separate axis-threshold-as-button hack.

**Confirmed = the computed drive speed (frac_left/frac_right, after
deadzone) changed since the last tick, OR LT's raw axis value changed
by more than LT_CHANGE_THRESHOLD (0.05) since the last tick.** Either
source resets the confirmation window (--confirm-timeout, 10s
default). No dedicated arming button and no special first-touch gate
tied to LT specifically — ordinary driving (steering, accelerating,
braking) already keeps re-confirming on its own via the drive-stick
check, so nothing needs to be pressed during normal use. LT exists
specifically for the one case ordinary driving doesn't cover: holding
a constant, unchanging speed (including pinned full-throttle) for
longer than the timeout — nudge LT slightly to reconfirm without
touching the drive stick.

This still protects against the original concern (a frozen/stale HID
report from the F710's proprietary dongle silently continuing to
report old data): a genuine freeze holds *every* axis bit-identical,
so both change checks correctly see "nothing changed" and correctly
expire. Idle-noise risk considered and judged low: calibration
captures showed LT sitting at a rock-stable exact 0.0 across dozens of
consecutive ticks whenever untouched, so the 0.05 threshold isn't
fighting sensor jitter.

Before any input has ever changed (startup) and any time the window
has expired, both motors are held at (or ramped to) 0 — driving only
resumes once a change is detected again. **If nothing is currently
commanded (both motors already at 0), an expired window does nothing
further** — no ramp-down runs from a standing stop, only from an
actually nonzero commanded speed.

On expiry from a nonzero speed: a staged ramp-down (RAMP_STEPS/
RAMP_DURATION, own small implementation here — not imported from
capture_step_response.py's _soft_stop(), matching this project's
established "duplicate small adapted logic rather than couple a
production driving process to a characterization/test tool" pattern),
not an abrupt `speed 0`. Ramps each motor independently from its own
last commanded speed (left/right can legitimately differ under
differential drive).

## Poll/send rate — 200ms, lowered from the initial 500ms (Issue #23)

Every tick, whatever this loop currently wants each motor doing (live
computed speed, or 0 while unconfirmed/ramping) is sent unconditionally
— this also serves as the watchdog's own IDLE_TIMEOUT (20s) heartbeat,
so a steadily-held stick position alone never risks an idle stop.
500ms was the deliberately conservative starting value for the first
live build (before real bus headroom was known). Issue #24's LIN bus
stress test (2026-09-22) found the bus stays completely clean (zero
scheduling lag, zero firmware-side counter deltas) down to 0.05s, with
the real structural floor somewhere between 0.03s and 0.05s — so
--poll-interval was lowered to **0.2s**, not all the way to the 100ms
originally discussed in Issue #23, by deliberate choice: the user
wants headroom against that measured floor, not to run right at the
edge of what's been confirmed safe.

## Recovery trigger (Issue #21) — user-initiated, nothing automatic

The red **B** button (calibrated as --recovery-button, index 1 — see
Issue #19/#21's calibration comments) fires a recovery attempt on
press (edge-detected — a fresh press, not a held state, so it can't
re-fire every tick while held). **A press has no effect unless at
least one motor is actually stalled** (checked live via `status`'s
latched STALL_TIM_ERR, same check `capture_step_response.py`'s
`_confirm_stall` uses) — the core safety property from the original
design.

**Flow on a real stall:** reset the stalled motor(s) (selectivity —
clears the watchdog's own stall bookkeeping before anything else
touches it, same reasoning as Issue #4) → a recovery sequence from
GENTLE_STRATEGIES on each stalled motor (sequentially if both are
stalled, not simultaneously) → a joint verification step, `speed 800`
on **both** motors together for 1.5s, sampling `rpm` at 1.0s and 1.5s
checkpoints (mirrors `capture_step_response.py`'s `rpm_1s`/`rpm_1p5s`
two-checkpoint pattern, including its Hall-chatter-false-positive
catch via `status_after_retry`), then a staged ramp-down (reuses
`_ramp_down_both()`, not an abrupt `speed 0` — both motors are
genuinely running at speed here) → logged to `recovery_sequences.csv`
→ control returns to the joystick. Both motors are driven together in
the verification step, deliberately, even if only one stalled — #19's
stop-all policy means both were already sitting at 0, and testing only
the recovered side would visibly lurch/spin a real vehicle
asymmetrically.

**GENTLE_STRATEGIES is a subset of `capture_step_response.py`'s own
`STRATEGIES` catalog — the full-power ones (`speed_max_plus`/
`speed_max_minus`, `burst_cw`/`burst_ccw`) are deliberately excluded
here**, not gated behind an extra confirmation prompt. Reasoning: a
human may be standing right next to a real vehicle during a live
recovery attempt, unlike the bench-rig context those aggressive
strategies were designed for — a smaller, inherently gentler catalog
resolves that concern without adding friction to an already-urgent
action.

**The whole flow blocks the main loop** — stick input is completely
ignored for its ~2-3s duration, same pattern the dead-man ramp-down
already uses. No extra consent prompt — runs entirely within the
already-`--live`-consented joystick session.

`recovery_sequences.csv`'s schema (`RECOVERY_LOG_PATH`/
`RECOVERY_LOG_FIELDS`/`_append_recovery_row`) is imported from
`capture_step_response.py`, not duplicated — see that file's own
comment for why this one piece is a deliberate exception to the
"duplicate small logic" pattern used everywhere else the two scripts'
behavior diverges: the file itself is a single shared, growing
dataset, and two independently-drifting field-list copies would
misalign its columns.

## Explicitly out of scope here

Controller/other feedback on a stall is Issue #22 — not implemented
in this script yet.
"""
import argparse
import datetime
import logging
import random
import re
import sys
import time
from multiprocessing.connection import Client

from capture_step_response import _append_recovery_row

try:
    # Not installable via pip on this Windows/Python-3.14 dev machine as
    # of 2026-09-21 (no prebuilt wheel yet) -- guarded the same way
    # motorcontrol.py guards its readline import, so this module (and
    # its pure, pygame-free functions) stay importable/testable locally.
    # Confirmed present on the Pi (1.9.4.post1). run() checks for this
    # explicitly and fails clearly if it's ever missing there.
    import pygame
except ImportError:
    pygame = None

import logsetup
from motorcontrol import SOCKET_ADDRESS

LOG_PATH = "joystick.log"
logger = logging.getLogger("joystick")

MAX_RPM_DEFAULT = 1200
DEADZONE_DEFAULT = 500
CONFIRM_TIMEOUT_DEFAULT = 10.0
POLL_INTERVAL_DEFAULT = 0.2  # see Issue #23/#24 -- lowered from the initial 0.5, kept above the ~0.03-0.05s measured LIN floor for margin
AXIS_FORWARD_DEFAULT = 4  # right stick, away-from-body axis -- see module docstring's calibration note
AXIS_STEER_DEFAULT = 3    # right stick, left/right axis -- sign of left-vs-right not yet independently confirmed
AXIS_LT_DEFAULT = 2       # left trigger -- dead-man confirmation signal, not a drive input
LT_CHANGE_THRESHOLD_DEFAULT = 0.05  # raw axis units -- see "Dead-man confirmation" section
JOYSTICK_INDEX_DEFAULT = 0

RAMP_STEPS = 5  # own small ramp, same shape as capture_step_response.py's _soft_stop() -- not imported, see module docstring
RAMP_DURATION = 1.0  # seconds

DIRECTION_SIGN = {"cw": 1, "ccw": -1}
MOTOR_INSTANCE_MIN = 0
MOTOR_INSTANCE_MAX = 3

# --- recovery trigger (Issue #21) -- see module docstring ---

RECOVERY_BUTTON_DEFAULT = 1  # red B, calibrated live 2026-09-23

# Mirrors STM32/firmware/Core/Inc/errors.h's STALL_TIM_ERR -- same
# duplicated-by-hand constant as capture_step_response.py's own copy
# (see that file's comment for why: no shared generation mechanism for
# error codes the way addresses.json provides for PIDs).
STALL_TIM_ERR = -65

RPM_RE = re.compile(r"rpm=(-?\d+)")
SYS_ERROR_RE = re.compile(r"sys_error=(-?\d+)")

# Deliberate SUBSET of capture_step_response.py's STRATEGIES -- the
# full-power ones (speed_max_plus/minus, burst_cw/ccw) are excluded
# here, not gated behind an extra confirmation, see module docstring.
GENTLE_STRATEGIES = {
    "speed_plus": {"kind": "speed", "value": 500},
    "speed_minus": {"kind": "speed", "value": -500},
    "pulse_plus": {"kind": "pulse", "value": 1000},
    "pulse_minus": {"kind": "pulse", "value": -1000},
}
SEQUENCE_MIN_LEN = 2
SEQUENCE_MAX_LEN = 3
SEQUENCE_STEP_PAUSE_S = 0.1  # minimum pause between any two sequence steps
SPEED_STRATEGY_HOLD_S = 0.5  # how long a "speed" strategy holds before its speed-0 cleanup
SEQUENCE_MAX_PULSE = 2  # per sequence, total -- same cap capture_step_response.py applies to its larger catalog

VERIFY_SPEED = 800  # joint verification step, both motors, see module docstring
VERIFY_CHECKPOINT_1_S = 1.0
VERIFY_CHECKPOINT_2_S = 1.5


class _OnceAction(argparse.Action):
    # A repeated CLI flag (e.g. two --left) would otherwise silently
    # keep only the last value -- the same class of bug that caused a
    # real live mixup in capture_step_response.py (see Issue #4's
    # write-up in raspi/CLAUDE.md). Reimplemented here rather than
    # imported, matching this project's "duplicate small adapted logic
    # across differently-lifecycled scripts" pattern.
    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, f"_seen_{self.dest}", False):
            parser.error(f"{option_string} given more than once")
        setattr(namespace, f"_seen_{self.dest}", True)
        setattr(namespace, self.dest, values)


class _RealSender:
    """Sends commands over a persistent IPC connection to the watchdog --
    same connection-per-session model motorcontrol.py uses, so the
    watchdog's is-the-supervisor-alive check (on_connect/on_disconnect)
    works the same way here as it does for that script."""

    def __init__(self, address):
        self._conn = Client(address, family='AF_UNIX')

    def send(self, command):
        # Generic send (added 2026-09-23 for Issue #21's recovery flow --
        # status/reset/hal/rpm/pulse, not just speed) -- send_speed()
        # below is a thin wrapper kept for the main loop's existing calls.
        logger.info(f"-> {command}")
        self._conn.send(command)
        reply = self._conn.recv()
        logger.info(f"<- {reply}")
        return reply

    def send_speed(self, instance, value):
        return self.send(f"speed {instance} {value}")

    def close(self):
        self._conn.close()


class _SimulateSender:
    """Default sender -- never opens the IPC connection at all, just
    prints/logs the command that would have been sent."""

    def send(self, command):
        logger.info(f"[SIMULATE] {command}")
        return "SIMULATED"

    def send_speed(self, instance, value):
        return self.send(f"speed {instance} {value}")

    def close(self):
        pass


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _apply_deadzone(value, deadzone):
    return 0 if abs(value) < deadzone else value


def _compute_speeds(forward, steer, max_rpm, deadzone, left_sign, right_sign):
    """Pure differential-drive computation, no pygame/IPC involved --
    the piece this module's own docstring formula describes. Kept
    standalone so it's directly unit-testable."""
    frac_left = _clamp(forward + steer, -1.0, 1.0)
    frac_right = _clamp(forward - steer, -1.0, 1.0)
    speed_left = _apply_deadzone(round(frac_left * max_rpm) * left_sign, deadzone)
    speed_right = _apply_deadzone(round(frac_right * max_rpm) * right_sign, deadzone)
    return speed_left, speed_right


def _value_changed(previous, current, threshold=0):
    # Shared by both dead-man confirmation sources (see module
    # docstring): threshold=0 for the already-quantized drive speeds
    # (any different integer counts), LT_CHANGE_THRESHOLD for LT's raw
    # float reading (needs a real margin, not exact-float comparison).
    return abs(current - previous) > threshold


def _is_confirmed(last_confirm_time, now, timeout):
    if last_confirm_time is None:
        return False  # nothing has changed yet -- held at 0 until the first detected change
    return (now - last_confirm_time) <= timeout


def _ramp_down_both(sender, left_instance, right_instance, left_speed, right_speed,
                     steps=RAMP_STEPS, duration=RAMP_DURATION, sleep_fn=time.sleep):
    # Descends both motors together (interleaved sends each step), not
    # one fully then the other -- matches Issue #19's "each motor ramps
    # from its own current commanded speed" design. Last step (i=0)
    # lands exactly on 0 for both, so no separate final `speed 0` send
    # is needed afterward (unlike capture_step_response.py's
    # _soft_stop(), which loops steps-1..1 then sends 0 once outside
    # the loop -- this folds that into one loop instead).
    step_interval = duration / steps
    for i in range(steps - 1, -1, -1):
        sender.send_speed(left_instance, round(left_speed * i / steps))
        sender.send_speed(right_instance, round(right_speed * i / steps))
        sleep_fn(step_interval)


def _read_rpm(sender, motor):
    match = RPM_RE.search(sender.send(f"rpm {motor}"))
    return int(match.group(1)) if match else None


def _is_stalled(sender, motor):
    # Same check as capture_step_response.py's _confirm_stall() -- rpm==0
    # alone isn't trusted, only a latched STALL_TIM_ERR counts.
    status_reply = sender.send(f"status {motor}")
    match = SYS_ERROR_RE.search(status_reply)
    sys_error = int(match.group(1)) if match else None
    return sys_error == STALL_TIM_ERR


def _generate_gentle_sequence(rng=random):
    """Same generation shape as capture_step_response.py's
    _generate_recovery_sequence(), over the smaller GENTLE_STRATEGIES
    catalog -- no burst/fullspeed categories here, so only the
    no-immediate-repeat and per-sequence pulse cap apply."""
    length = rng.randint(SEQUENCE_MIN_LEN, SEQUENCE_MAX_LEN)
    names = list(GENTLE_STRATEGIES.keys())
    while True:
        sequence = []
        pulse_count = 0
        for _ in range(length):
            candidates = names[:]
            rng.shuffle(candidates)
            picked = None
            for name in candidates:
                kind = GENTLE_STRATEGIES[name]["kind"]
                if sequence and name == sequence[-1]:
                    continue
                if kind == "pulse" and pulse_count >= SEQUENCE_MAX_PULSE:
                    continue
                picked = name
                break
            if picked is None:
                break  # dead end -- restart the whole sequence
            sequence.append(picked)
            if GENTLE_STRATEGIES[picked]["kind"] == "pulse":
                pulse_count += 1
        if len(sequence) == length:
            return sequence


def _run_gentle_sequence(sender, motor, sleep_fn=time.sleep, rng=random):
    # Returns the exact command(s) sent, not just the strategy names --
    # same reasoning as capture_step_response.py's _execute_strategy():
    # the catalog's own values could change later, the log needs to
    # capture what was actually tried.
    sequence = _generate_gentle_sequence(rng)
    commands = []
    for name in sequence:
        strategy = GENTLE_STRATEGIES[name]
        if strategy["kind"] == "speed":
            cmd = f"speed {motor} {strategy['value']}"
            sender.send(cmd)
            commands.append(cmd)
            sleep_fn(SPEED_STRATEGY_HOLD_S)
            stop_cmd = f"speed {motor} 0"
            sender.send(stop_cmd)
            commands.append(stop_cmd)
        elif strategy["kind"] == "pulse":
            cmd = f"pulse {motor} {strategy['value']}"
            sender.send(cmd)
            commands.append(cmd)
        sleep_fn(SEQUENCE_STEP_PAUSE_S)
    return sequence, commands


def _handle_recovery_button(sender, left_instance, right_instance, sleep_fn=time.sleep, rng=random):
    """The full Issue #21 flow. Returns True if a stall was found and
    handled (caller resets its own speed-tracking state to 0), False if
    the press was a no-op (nothing was stalled)."""
    left_stalled = _is_stalled(sender, left_instance)
    right_stalled = _is_stalled(sender, right_instance)
    if not left_stalled and not right_stalled:
        logger.info("recovery button pressed -- no stall detected, no-op")
        return False

    stalled = [i for i, is_it in ((left_instance, left_stalled), (right_instance, right_stalled)) if is_it]
    logger.warning(f"recovery button pressed -- stalled motor(s): {stalled}")
    seq_timestamp = datetime.datetime.now().isoformat()

    for motor in stalled:
        # Reset FIRST -- selectivity, same reasoning as Issue #4: clears
        # the watchdog's own stall bookkeeping for this instance before
        # anything else touches it, so its background stall check has
        # nothing left to see during the sequence below.
        hal_before = sender.send(f"hal {motor}")
        status_before = sender.send(f"status {motor}")
        sender.send(f"reset {motor}")
        sequence, commands = _run_gentle_sequence(sender, motor, sleep_fn, rng)
        hal_after = sender.send(f"hal {motor}")
        status_after = sender.send(f"status {motor}")
        _append_recovery_row({
            "timestamp": seq_timestamp,
            "phase": "sequence",
            "motor_instance": motor,
            "hal_before_sequence": hal_before,
            "status_before_sequence": status_before,
            "sequence": ";".join(commands),
            "hal_after_sequence": hal_after,
            "status_after_sequence": status_after,
            "source": "joystick",
        })

    # Joint verification step, both motors together -- deliberately, even
    # if only one stalled (see module docstring: #19's stop-all policy
    # means both were already at 0, testing only one side would lurch a
    # real vehicle asymmetrically).
    sender.send_speed(left_instance, VERIFY_SPEED)
    sender.send_speed(right_instance, VERIFY_SPEED)
    sleep_fn(VERIFY_CHECKPOINT_1_S)
    rpm_left_1s = _read_rpm(sender, left_instance)
    rpm_right_1s = _read_rpm(sender, right_instance)
    sleep_fn(VERIFY_CHECKPOINT_2_S - VERIFY_CHECKPOINT_1_S)
    rpm_left_1p5s = _read_rpm(sender, left_instance)
    rpm_right_1p5s = _read_rpm(sender, right_instance)
    status_after_retry = f"{sender.send(f'status {left_instance}')}/{sender.send(f'status {right_instance}')}"
    # Staged ramp-down, not an abrupt speed 0 -- both motors are
    # genuinely running at VERIFY_SPEED here, and an abrupt stop after a
    # sustained run was observed live (capture_step_response.py,
    # 2026-08-20) to stop harder than a plain coast-down (the PI
    # controller reacting to a sudden large negative error). Reuses the
    # main loop's own _ramp_down_both() -- both motors happen to share
    # the same starting speed here, unlike the dead-man timeout case.
    _ramp_down_both(sender, left_instance, right_instance, VERIFY_SPEED, VERIFY_SPEED, sleep_fn=sleep_fn)

    _append_recovery_row({
        "timestamp": seq_timestamp,
        "phase": "retry",
        "motor_instance": "both",
        "rpm_1s": f"{rpm_left_1s}/{rpm_right_1s}",
        "rpm_1p5s": f"{rpm_left_1p5s}/{rpm_right_1p5s}",
        "status_after_retry": status_after_retry,
        "source": "joystick",
    })
    return True


def _build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Joystick-driven dual-motor control (Issue #19). "
                     "Defaults to --simulate (no motor movement) -- pass --live to actually drive.")
    parser.add_argument("--left", type=int, required=True, action=_OnceAction,
                         help=f"motor instance mounted left ({MOTOR_INSTANCE_MIN}-{MOTOR_INSTANCE_MAX})")
    parser.add_argument("--right", type=int, required=True, action=_OnceAction,
                         help=f"motor instance mounted right ({MOTOR_INSTANCE_MIN}-{MOTOR_INSTANCE_MAX})")
    parser.add_argument("--left-dir", choices=("cw", "ccw"), required=True, action=_OnceAction,
                         help="cw = no sign flip, ccw = flip -- see module docstring")
    parser.add_argument("--right-dir", choices=("cw", "ccw"), required=True, action=_OnceAction,
                         help="cw = no sign flip, ccw = flip -- see module docstring")
    parser.add_argument("--live", action="store_true",
                         help="actually connect to the watchdog and drive motors (default: simulate only)")
    parser.add_argument("--max-rpm", type=int, default=MAX_RPM_DEFAULT)
    parser.add_argument("--deadzone", type=int, default=DEADZONE_DEFAULT)
    parser.add_argument("--confirm-timeout", type=float, default=CONFIRM_TIMEOUT_DEFAULT)
    parser.add_argument("--axis-forward", type=int, default=AXIS_FORWARD_DEFAULT)
    parser.add_argument("--axis-steer", type=int, default=AXIS_STEER_DEFAULT)
    parser.add_argument("--axis-lt", type=int, default=AXIS_LT_DEFAULT,
                         help="dead-man confirmation axis (left trigger) -- see module docstring")
    parser.add_argument("--lt-change-threshold", type=float, default=LT_CHANGE_THRESHOLD_DEFAULT)
    parser.add_argument("--recovery-button", type=int, default=RECOVERY_BUTTON_DEFAULT,
                         help="stall-recovery trigger (red B) -- see module docstring, Issue #21")
    parser.add_argument("--poll-interval", type=float, default=POLL_INTERVAL_DEFAULT)
    parser.add_argument("--joystick-index", type=int, default=JOYSTICK_INDEX_DEFAULT)
    parser.add_argument("--debug", action="store_true",
                         help="print every raw axis value + button state each tick -- use this first to "
                              "calibrate --axis-forward/--axis-steer/--axis-lt on real hardware")
    return parser


def parse_args(argv=None):
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    if args.left == args.right:
        parser.error("--left and --right must be different motor instances")
    for name, value in (("--left", args.left), ("--right", args.right)):
        if not (MOTOR_INSTANCE_MIN <= value <= MOTOR_INSTANCE_MAX):
            parser.error(f"{name} out of range ({MOTOR_INSTANCE_MIN}..{MOTOR_INSTANCE_MAX})")
    return args


def run(args):
    if pygame is None:
        logger.error("pygame is not installed -- cannot read the joystick")
        sys.exit(1)

    sender = _RealSender(SOCKET_ADDRESS) if args.live else _SimulateSender()
    logger.info(f"mode: {'LIVE' if args.live else 'simulate (no motor movement)'}")

    pygame.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        logger.error("no joystick found")
        sender.close()
        sys.exit(1)

    joystick = pygame.joystick.Joystick(args.joystick_index)
    joystick.init()
    num_axes = joystick.get_numaxes()
    num_buttons = joystick.get_numbuttons()
    logger.info(f"joystick: {joystick.get_name()!r}, axes={num_axes}, buttons={num_buttons}")

    for label, index in (
        ("--axis-forward", args.axis_forward),
        ("--axis-steer", args.axis_steer),
        ("--axis-lt", args.axis_lt),
    ):
        if not (0 <= index < num_axes):
            logger.error(f"{label}={index} out of range for this controller (0..{num_axes - 1})")
            pygame.quit()
            sender.close()
            sys.exit(1)
    if not (0 <= args.recovery_button < num_buttons):
        logger.error(f"--recovery-button={args.recovery_button} out of range for this controller "
                     f"(0..{num_buttons - 1})")
        pygame.quit()
        sender.close()
        sys.exit(1)

    left_sign = DIRECTION_SIGN[args.left_dir]
    right_sign = DIRECTION_SIGN[args.right_dir]

    sent_speed_left = 0
    sent_speed_right = 0
    prev_speed_left = 0
    prev_speed_right = 0
    prev_lt = 0.0
    last_confirm_time = None
    recovery_button_was_pressed = False

    try:
        while True:
            pygame.event.pump()

            recovery_pressed = bool(joystick.get_button(args.recovery_button))
            recovery_edge = recovery_pressed and not recovery_button_was_pressed
            recovery_button_was_pressed = recovery_pressed
            if recovery_edge:
                # Blocking -- stick input ignored for the ~2-3s this
                # takes, same pattern the dead-man ramp-down already
                # uses. Either way (handled or no-op), both motors are
                # logically at 0 by the time this returns -- a real
                # stall already had them there, and a handled one ends
                # with an explicit speed 0 on both (see module docstring).
                _handle_recovery_button(sender, args.left, args.right)
                sent_speed_left = sent_speed_right = 0
                prev_speed_left = prev_speed_right = 0
                time.sleep(args.poll_interval)
                continue

            forward = -joystick.get_axis(args.axis_forward)
            steer = joystick.get_axis(args.axis_steer)
            candidate_left, candidate_right = _compute_speeds(
                forward, steer, args.max_rpm, args.deadzone, left_sign, right_sign)
            lt = joystick.get_axis(args.axis_lt)

            if (_value_changed(prev_speed_left, candidate_left)
                    or _value_changed(prev_speed_right, candidate_right)
                    or _value_changed(prev_lt, lt, args.lt_change_threshold)):
                last_confirm_time = time.monotonic()
            prev_speed_left, prev_speed_right, prev_lt = candidate_left, candidate_right, lt

            confirmed = _is_confirmed(last_confirm_time, time.monotonic(), args.confirm_timeout)

            if args.debug:
                raw_axes = [round(joystick.get_axis(i), 3) for i in range(num_axes)]
                raw_buttons = [int(joystick.get_button(i)) for i in range(num_buttons)]
                logger.info(f"[DEBUG] axes={raw_axes} buttons={raw_buttons} confirmed={confirmed}")

            if confirmed:
                speed_left, speed_right = candidate_left, candidate_right
            else:
                if sent_speed_left != 0 or sent_speed_right != 0:
                    logger.warning("no/expired dead-man confirmation -- ramping down")
                    _ramp_down_both(sender, args.left, args.right, sent_speed_left, sent_speed_right)
                speed_left, speed_right = 0, 0

            sender.send_speed(args.left, speed_left)
            sender.send_speed(args.right, speed_right)
            sent_speed_left, sent_speed_right = speed_left, speed_right

            time.sleep(args.poll_interval)
    except KeyboardInterrupt:
        logger.info("shutting down (Ctrl+C) -- ramping down")
        _ramp_down_both(sender, args.left, args.right, sent_speed_left, sent_speed_right)
    finally:
        pygame.quit()
        sender.close()


def main():
    args = parse_args()
    logsetup.configure("joystick", LOG_PATH, terminal_level=logging.INFO)
    run(args)


if __name__ == "__main__":
    main()
