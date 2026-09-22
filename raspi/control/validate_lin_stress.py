"""LIN bus stress/soak test (Issue #24). Standalone, real hardware, not a
pytest test case (see raspi/CLAUDE.md's Test Suite Policy) -- run() takes
injectable sleep_fn/clock_fn specifically so its scheduling logic itself
IS pytest-testable against a fake clock, without waiting the real 60s.

Motivated by a real observation during Issue #19's live joystick test: one
motor took nearly a second to visibly start responding to a nonzero speed
command at the joystick's 500ms poll rate. Working theory (not confirmed):
the watchdog serializes *every* LIN bus access -- its own background poll
thread and every client command -- through one lock, so a `speed` write
could sit queued behind in-flight reads under load, delaying when it
actually reaches the wire. This script tests that directly, and more
generally looks for the point where each device's own LIN implementation
starts struggling under sustained traffic (the current sensor's ~1s
onboard ADC averaging window makes it the suspected weaker link, but
nothing here assumes that up front).

## Design (settled by discussion, see Issue #24)

`speed 0` deliberately, never a nonzero value -- exercises the real
write path (sync/PID/data/checksum/echo-compare) at full rate without
ever actually moving the motor, keeping this close to risk-free despite
technically still being a `speed` command. One lightweight y/N prompt at
the start (Motor Execution Consent), not a full pre-flight checklist.

Two independent cadences, so the current-sensor-specific rate can be
swept while the motor-stress rate stays fixed (the whole point --
isolating which device is the weaker link):
- **--tick-rate (required, no default):** every tick, for BOTH motor
  instances: `speed <instance> 0`, `rpm <instance>`, `status <instance>`
  -- 6 LIN transactions per tick, the main stress load.
- **--secondary-tick-rate (default 2.0s):** `hal <instance>` for both
  motors, plus `current`/`errors` for the current sensor. Deliberately
  decoupled from --tick-rate -- the current sensor's own onboard
  averaging window is already ~1s (see CURRENT_SAMPLE_INTERVAL elsewhere
  in this codebase), so sampling it faster than that wouldn't reveal
  anything new regardless of how aggressive the main load is.

**--duration (default 60.0s, added 2026-09-22)** -- longer runs (e.g.
10 minutes) can surface slow-onset degradation a 60s soak wouldn't
(thermal drift, gradual counter creep) that this never moved the motor
either way, so there's no extra risk/consent implication from a longer
run. Still one confirmation per run, one tick-rate/duration combination
at a time -- compare different values by re-running the script (same
convention as run_grid_row.py), not an automatic sweep.

`reset` for both motors as the very first commands -- clean baseline
(clears controlvariableinput/integral/sysError, see watchdog.py's own
"reset" comment). The current sensor has no reset verb at all (motor-
only, see MOTOR_INSTANCE_VERBS in watchdog.py) -- its "reset" here is
just an initial `errors` read establishing this run's own starting
point, same idea applied to `status`'s timeout/checksum counters for
both motors (not assumed to already be exactly zero after `reset`,
since that command's own docstring doesn't specifically claim it clears
those two counters, only sysError/integral).

## Failure/degradation detection -- reuse existing tools, don't reinvent

- Every reply checked as it's logged (`_is_ok_reply()`): `speed`/`reset`
  succeed with a bare `"OK"` (no `ret=` field at all), every read verb
  (`rpm`/`status`/`hal`/`current`/`errors`) succeeds with `"OK ret=0
  ..."` -- both forms count, anything else doesn't. (An earlier version
  only recognized the second form and flagged every single successful
  `speed 0` as a false-positive warning -- caught live 2026-09-22 on a
  real 60s/0.5s run, 240 warnings, all of them this bug, none of them
  real.) A scheduling-lag WARNING is also logged live if a tick can't be
  started on time (the round-trip cost of the previous batch already
  exceeded the requested interval) -- itself a form of degradation
  worth seeing directly.
- Before/after delta on firmware-side counters (motor `status`'s
  timeout/checksum counts, current sensor's `errors` ring buffer),
  logged AND printed in the end-of-run summary -- authoritative evidence
  the firmware itself registered a problem, independent of whether the
  client noticed anything during the run. Logged as well as printed
  (added 2026-09-22) since the printed summary goes to stderr, which a
  `... | tee run.csv` capture (stdout only) would otherwise lose.
- Full command/reply trace goes to validate_lin_stress.log as always;
  run analyze_logs.py / the /analyze-logs skill against it afterward for
  the detailed pass -- already flags unmatched calls, non-zero ret
  codes, latency outliers, WARNING/ERROR lines. Not reimplemented here.

Prints CSV (elapsed_ms,command,latency_ms,reply) to stdout, one row per
LIN command -- same "stdout reserved for CSV, log file has full detail"
convention as validate_speed.py. The end-of-run summary (counter deltas,
total/error counts) goes to stderr so it doesn't pollute the CSV stream.
"""
import argparse
import csv
import logging
import re
import sys
import time
from multiprocessing.connection import Client

import logsetup
from motorcontrol import SOCKET_ADDRESS

LOG_PATH = "validate_lin_stress.log"
logger = logging.getLogger("validate_lin_stress")

MOTOR_INSTANCES = (0, 1)
CURRENT_INSTANCE = 0
DURATION_S = 60.0
SECONDARY_TICK_RATE_DEFAULT = 2.0

STATUS_RE = re.compile(
    r"ret=(-?\d+) timeout=(-?\d+) checksum=(-?\d+) kickstart=(-?\d+) sys_error=(-?\d+)")
ERRORS_RE = re.compile(r"ret=(-?\d+) codes=(\[[^\]]*\])")


def _send(conn, command):
    logger.info(f"-> {command}")
    conn.send(command)
    reply = conn.recv()
    logger.info(f"<- {reply}")
    return reply


def _parse_status(reply):
    """Pure parser for the `status` reply. Returns a dict, or None if the
    reply doesn't match (e.g. a comms error mid-run) -- callers must
    handle None rather than assume every read succeeds."""
    match = STATUS_RE.search(reply)
    if not match:
        return None
    ret, timeout, checksum, kickstart, sys_error = (int(g) for g in match.groups())
    return {"ret": ret, "timeout": timeout, "checksum": checksum,
            "kickstart": kickstart, "sys_error": sys_error}


def _parse_error_codes(reply):
    """Pure parser for the `errors` reply's codes=[...] list. Returns the
    list of ints, or None if unparseable or ret!=0."""
    match = ERRORS_RE.search(reply)
    if not match:
        return None
    ret = int(match.group(1))
    if ret != 0:
        return None
    codes_str = match.group(2).strip("[]")
    return [int(x) for x in codes_str.split(",") if x.strip()]


def _status_delta(before, after):
    """Pure before/after diff -- None propagates rather than raising, so
    one unparseable snapshot doesn't crash the whole summary."""
    if before is None or after is None:
        return None
    return {key: after[key] - before[key] for key in ("timeout", "checksum", "kickstart")}


def _is_ok_reply(reply):
    # "speed"/"reset" reply with a bare "OK" on success (no ret= field at
    # all) -- every read verb (rpm/status/hal/current/errors) replies
    # "OK ret=0 ...". Both forms count as success; anything else (a
    # ret!=0, a timeout placeholder, a malformed/empty reply) doesn't.
    return reply == "OK" or "ret=0" in reply


def _timed_send(conn, command, rows, start_time, clock_fn):
    t0 = clock_fn()
    reply = _send(conn, command)
    latency_ms = (clock_fn() - t0) * 1000
    if not _is_ok_reply(reply):
        logger.warning(f"non-zero/unparseable ret on {command!r}: {reply}")
    rows.append({
        "elapsed_ms": round((clock_fn() - start_time) * 1000),
        "command": command,
        "latency_ms": round(latency_ms, 1),
        "reply": reply,
    })
    return reply


def _main_tick_commands(conn, rows, start_time, clock_fn):
    for instance in MOTOR_INSTANCES:
        _timed_send(conn, f"speed {instance} 0", rows, start_time, clock_fn)
        _timed_send(conn, f"rpm {instance}", rows, start_time, clock_fn)
        _timed_send(conn, f"status {instance}", rows, start_time, clock_fn)


def _secondary_tick_commands(conn, rows, start_time, clock_fn):
    for instance in MOTOR_INSTANCES:
        _timed_send(conn, f"hal {instance}", rows, start_time, clock_fn)
    _timed_send(conn, f"current {CURRENT_INSTANCE}", rows, start_time, clock_fn)
    _timed_send(conn, f"errors {CURRENT_INSTANCE}", rows, start_time, clock_fn)


def run(tick_rate, secondary_tick_rate=SECONDARY_TICK_RATE_DEFAULT,
        duration=DURATION_S, conn=None, address=SOCKET_ADDRESS,
        sleep_fn=time.sleep, clock_fn=time.monotonic):
    # conn injectable for tests (a fake, no real IPC) -- opens a real
    # Client itself otherwise, closed on the way out either way it came in.
    owns_conn = conn is None
    if owns_conn:
        conn = Client(address, family='AF_UNIX')
    try:
        logger.info(f"tick_rate={tick_rate}s secondary_tick_rate={secondary_tick_rate}s "
                    f"duration={duration}s motors={MOTOR_INSTANCES} current={CURRENT_INSTANCE}")

        for instance in MOTOR_INSTANCES:
            _send(conn, f"reset {instance}")

        status_before = {i: _parse_status(_send(conn, f"status {i}")) for i in MOTOR_INSTANCES}
        errors_before = _parse_error_codes(_send(conn, f"errors {CURRENT_INSTANCE}"))

        rows = []
        start_time = clock_fn()
        end_time = start_time + duration
        next_main_tick = start_time
        next_secondary_tick = start_time

        while True:
            now = clock_fn()
            if now >= end_time:
                break
            if now >= next_main_tick:
                if now > next_main_tick + tick_rate:
                    logger.warning(
                        f"main tick falling behind schedule -- due at "
                        f"{next_main_tick - start_time:.2f}s, running at {now - start_time:.2f}s")
                _main_tick_commands(conn, rows, start_time, clock_fn)
                next_main_tick += tick_rate
            if now >= next_secondary_tick:
                if now > next_secondary_tick + secondary_tick_rate:
                    logger.warning(
                        f"secondary tick falling behind schedule -- due at "
                        f"{next_secondary_tick - start_time:.2f}s, running at {now - start_time:.2f}s")
                _secondary_tick_commands(conn, rows, start_time, clock_fn)
                next_secondary_tick += secondary_tick_rate
            sleep_until = min(next_main_tick, next_secondary_tick, end_time)
            remaining = sleep_until - clock_fn()
            if remaining > 0:
                sleep_fn(remaining)

        status_after = {i: _parse_status(_send(conn, f"status {i}")) for i in MOTOR_INSTANCES}
        errors_after = _parse_error_codes(_send(conn, f"errors {CURRENT_INSTANCE}"))
    finally:
        if owns_conn:
            conn.close()

    summary = {
        "status_before": status_before, "status_after": status_after,
        "status_delta": {i: _status_delta(status_before[i], status_after[i]) for i in MOTOR_INSTANCES},
        "errors_before": errors_before, "errors_after": errors_after,
        "errors_changed": errors_before != errors_after,
    }
    # Also logged (not just printed to stderr) -- the printed summary is
    # otherwise only visible live and unrecoverable afterward unless the
    # caller happened to capture stderr too (found live 2026-09-22: a run
    # piped as `... | tee run.csv` only captures stdout's CSV, the
    # stderr-only summary would have been lost without this).
    logger.info(f"summary: {summary}")
    return rows, summary


def _print_results(rows, summary):
    writer = csv.writer(sys.stdout)
    writer.writerow(["elapsed_ms", "command", "latency_ms", "reply"])
    for row in rows:
        writer.writerow([row["elapsed_ms"], row["command"], row["latency_ms"], row["reply"]])

    print("\n--- summary ---", file=sys.stderr)
    for instance in MOTOR_INSTANCES:
        print(f"motor {instance}: before={summary['status_before'][instance]} "
              f"after={summary['status_after'][instance]} "
              f"delta={summary['status_delta'][instance]}", file=sys.stderr)
    changed = "CHANGED" if summary["errors_changed"] else "unchanged"
    print(f"current sensor {CURRENT_INSTANCE}: before={summary['errors_before']} "
          f"after={summary['errors_after']} ({changed})", file=sys.stderr)
    bad = sum(1 for r in rows if not _is_ok_reply(r["reply"]))
    print(f"{len(rows)} commands sent, {bad} with a non-zero/unparseable ret "
          f"-- see validate_lin_stress.log / analyze_logs.py for detail", file=sys.stderr)


def _build_arg_parser():
    parser = argparse.ArgumentParser(
        description="LIN bus stress/soak test (Issue #24). speed 0 (never moves the motor)/"
                     "rpm/status on both motors at --tick-rate; hal/current/errors at "
                     "--secondary-tick-rate; for --duration seconds.")
    parser.add_argument("--tick-rate", type=float, required=True,
                         help="seconds between the main battery (speed 0/rpm/status, both motors)")
    parser.add_argument("--secondary-tick-rate", type=float, default=SECONDARY_TICK_RATE_DEFAULT,
                         help=f"seconds between hal/current/errors (default {SECONDARY_TICK_RATE_DEFAULT})")
    parser.add_argument("--duration", type=float, default=DURATION_S,
                         help=f"seconds the stress test runs (default {DURATION_S:.0f}, "
                              f"added 2026-09-22 -- was a fixed 60s only)")
    return parser


def parse_args(argv=None):
    return _build_arg_parser().parse_args(argv)


def main():
    args = parse_args()
    logsetup.configure("validate_lin_stress", LOG_PATH, terminal_level=None)
    print(f"About to stress the LIN bus for {args.duration:.0f}s: speed 0 (never moves the "
          f"motor)/rpm/status on motors {MOTOR_INSTANCES} every {args.tick_rate}s, "
          f"hal/current/errors every {args.secondary_tick_rate}s.", file=sys.stderr)
    # input()'s own prompt argument writes to stdout regardless of this
    # print() convention -- found live 2026-09-22, corrupting run.csv's
    # header when piped through `| tee run.csv` ("Proceed? [y/N]
    # elapsed_ms,command,..." on one line). Printed to stderr explicitly
    # instead, input() called with no prompt of its own.
    print("Proceed? [y/N] ", end="", flush=True, file=sys.stderr)
    if input().strip().lower() != "y":
        print("aborted", file=sys.stderr)
        sys.exit(0)
    rows, summary = run(args.tick_rate, args.secondary_tick_rate, args.duration)
    _print_results(rows, summary)


if __name__ == "__main__":
    main()
