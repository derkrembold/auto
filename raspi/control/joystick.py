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

## Explicitly out of scope here

Stall detection/recovery during live driving is Issue #21 (restrictive
policy: a stall just stops, the user triggers a recovery sequence
afterward — nothing automatic). Controller/other feedback on a stall
is Issue #22. Neither is implemented in this script yet.
"""
import argparse
import logging
import sys
import time
from multiprocessing.connection import Client

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
    """Sends `speed <instance> <value>` over a persistent IPC connection
    to the watchdog -- same connection-per-session model motorcontrol.py
    uses, so the watchdog's is-the-supervisor-alive check (on_connect/
    on_disconnect) works the same way here as it does for that script."""

    def __init__(self, address):
        self._conn = Client(address, family='AF_UNIX')

    def send_speed(self, instance, value):
        command = f"speed {instance} {value}"
        logger.info(f"-> {command}")
        self._conn.send(command)
        reply = self._conn.recv()
        logger.info(f"<- {reply}")
        return reply

    def close(self):
        self._conn.close()


class _SimulateSender:
    """Default sender -- never opens the IPC connection at all, just
    prints/logs the command that would have been sent."""

    def send_speed(self, instance, value):
        command = f"speed {instance} {value}"
        logger.info(f"[SIMULATE] {command}")
        return "SIMULATED"

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

    left_sign = DIRECTION_SIGN[args.left_dir]
    right_sign = DIRECTION_SIGN[args.right_dir]

    sent_speed_left = 0
    sent_speed_right = 0
    prev_speed_left = 0
    prev_speed_right = 0
    prev_lt = 0.0
    last_confirm_time = None

    try:
        while True:
            pygame.event.pump()

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
