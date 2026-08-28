#!/usr/bin/env python3
"""P/I grid search: 3x3 stencil around the firmware's KP/KI defaults --
like run_experiment.py, but for a whole sweep instead of one point.

Full design writeup lives in root CLAUDE.md's "Grid Search (run_grid.py)"
section -- read that for the reasoning behind every decision below, this
docstring only summarizes the mechanics.

Physical checklist -> P/I delta magnitude input -> one motor-start
consent covering the whole sweep (the user stays physically present
with a hand on the power supply for the duration -- that is what makes
a single upfront consent safe here, not a software prompt) -> 9 points
({-p_delta, 0, +p_delta} x {-i_delta, 0, +i_delta}, center = firmware
defaults) run via SSH against capture_step_response.py on the Pi, no
Saleae (see analysis/CLAUDE.md's Cost Function section for why) -> ISE
+ Mean Square Successive Difference, MSSD (2s and full-window, see
CLAUDE.md's Grid Search section) per point -> one results directory
for the whole sweep, not one per point -> matrices + grid_results.csv.

Usage:
    python3 run_grid.py [p_delta i_delta]

p_delta/i_delta are magnitudes (not signed deltas) -- prompted for
interactively if not given as positional args.

Range is deliberately NOT checked here beyond "is this a number" --
same reasoning as run_experiment.py: the watchdog's own validate()
(raspi/watchdog/watchdog.py's PI_DELTA_MIN/MAX, currently -1.28..1.27)
is the single source of truth, checked fresh by each of the 9 `pi`
sends. If any point's delta is rejected, the whole sweep aborts
immediately -- no partial/inconsistent grid is left lying around for
the future gradient search to misread.
"""
import csv
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
PI_HOST = "pi@motorpi.local"

# Must match raspi/control/capture_step_response.py's own TARGET_SPEED
# -- no shared-constants file crosses the Windows/Pi boundary in this
# project yet, same as PI_HOST/DEVICE_ID etc. being hardcoded per file.
TARGET_SPEED = 1000

# Thermal caution (power supply) + lets the motor reach genuine
# mechanical rest before the next point starts -- see CLAUDE.md's Grid
# Search section.
INTER_POINT_PAUSE_S = 4

# How much of the capture counts as "the rise/transient phase" for the
# short-window MSSD metric below -- see CLAUDE.md's Grid Search
# section, 2026-08-25 discussion: a hunting/oscillating rise (found by
# ear, then confirmed in a P+0.10,I+0.03 trace) isn't distinguishable
# from a smooth one by ISE alone, since ISE only scores distance from
# target, not how roughly the trace gets there.
MSSD_SHORT_WINDOW_S = 2.0

LOG_FETCH_RETRIES = 3

CHECKLIST = """
Physische Vorbereitung:
  - Motor-Stromversorgung/Batterie an.
  - Du bleibst fuer die GANZE 3x3-Runde koerperlich anwesend, Hand an
    der Stromversorgung, bereit sofort abzuschalten -- das deckt die
    Einwilligung fuer alle 9 Punkte ab (siehe CLAUDE.md's Grid Search
    Sektion), nicht ein einzelner Software-Prompt.
(STM32 laeuft und Watchdog laeuft --live werden unten automatisch
geprueft.)
"""


# Commutation state (0-5) from the 3 raw Hall bits (high/middle/low,
# i.e. PC0/PC1/PC2) -- mirrors STM32/firmware/Core/Src/main.c's
# getState()/driveStep() if-chain exactly, see that table for the
# meaning of each state. Built 2026-08-28 to test whether stiction
# likelihood correlates with the rotor's resting position before a
# step -- see analysis/grid_search_log.md's Dead Zone discussion. Only
# resolves the 6 electrical states, not which of the motor's 4
# mechanical pole-pair repetitions it is (that would need an absolute
# position reference this project doesn't have -- discussed, not built).
HALL_STATE_TABLE = {
    (1, 0, 0): 4,
    (1, 0, 1): 5,
    (0, 0, 1): 0,
    (0, 1, 1): 1,
    (0, 1, 0): 2,
    (1, 1, 0): 3,
}

HAL_RE = re.compile(r"data=\['(0x[0-9a-f]{2})', '(0x[0-9a-f]{2})', '(0x[0-9a-f]{2})'\]")


def _ssh_check(cmd):
    return subprocess.run(["ssh", PI_HOST, cmd], capture_output=True, text=True)


def _read_hal():
    # One-shot IPC call via motorcontrol.send_command(), same pattern
    # as _read_kickcount(). Returns (None, None) on any failure rather
    # than aborting the point over a nice-to-have diagnostic.
    cmd = ("cd /home/pi/auto && python3 -c "
           "\"import motorcontrol; print(motorcontrol.send_command('hal'))\"")
    result = _ssh_check(cmd)
    match = HAL_RE.search(result.stdout)
    if not match:
        return None, None
    bits = tuple(int(b, 16) for b in match.groups())
    return bits, HALL_STATE_TABLE.get(bits)


def _check_stm32_and_watchdog():
    result = _ssh_check("pgrep -af watchdog.py; echo '---'; tail -3 /home/pi/auto/watchdog.log")
    print(result.stdout)
    if "watchdog.py --live" not in result.stdout:
        sys.exit("Watchdog läuft nicht --live auf dem Pi. Abbruch.")
    if "ret=0" not in result.stdout:
        sys.exit("STM32 antwortet nicht (kein 'ret=0' in den letzten Log-Zeilen). Abbruch.")


def _confirm(prompt):
    return input(f"{prompt} [y/N]: ").strip().lower() == "y"


def _get_deltas():
    if len(sys.argv) == 3:
        try:
            return abs(float(sys.argv[1])), abs(float(sys.argv[2]))
        except ValueError:
            sys.exit("p_delta/i_delta müssen Zahlen sein.")
    while True:
        try:
            p_delta = abs(float(input("P delta (Betrag, z.B. 0.1): ").strip()))
            i_delta = abs(float(input("I delta (Betrag, z.B. 0.1): ").strip()))
            return p_delta, i_delta
        except ValueError:
            print("Bitte eine Zahl eingeben.")


def _point_name(p, i):
    return f"point_p{p:+.2f}_i{i:+.2f}"


def _send_speed_zero():
    # Belt-and-suspenders extra stop on top of the watchdog's own
    # disconnect-triggered stop -- see CLAUDE.md's Grid Search section,
    # Ctrl-C abort point 3. send_command() is motorcontrol.py's own
    # one-shot helper, built exactly for scripts like this one.
    cmd = ('cd /home/pi/auto && python3 -c '
           '"from motorcontrol import send_command; print(send_command(\'speed 0\'))"')
    result = _ssh_check(cmd)
    print(f"speed 0 (Abbruch-Absicherung): {result.stdout.strip() or result.stderr.strip()}")


def _read_kickcount():
    # Experimental/throwaway diagnostic for the firmware kick-start
    # mechanism (main.c's driveKickStart()) -- see watchdog.py's
    # "kickcount" verb / linbus.get_kick_start_count()'s docstring, and
    # run_experiment.py's own _read_kickcount() (same pattern, one-shot
    # IPC call via motorcontrol.send_command()). Returns None on any
    # failure rather than aborting the point over a nice-to-have.
    cmd = ("cd /home/pi/auto && python3 -c "
           "\"import motorcontrol; print(motorcontrol.send_command('kickcount'))\"")
    result = _ssh_check(cmd)
    match = re.search(r"kickcount=(\d+)", result.stdout)
    return int(match.group(1)) if match else None


def _run_point(p, i, run_dir, index, total):
    print(f"\nPunkt {index}/{total}: P delta={p:+.2f}, I delta={i:+.2f}")
    name = _point_name(p, i)
    csv_path = run_dir / f"{name}.csv"

    # Starting Hall/rotor position, before anything else touches the
    # motor this point -- see analysis/grid_search_log.md's Dead Zone
    # discussion (2026-08-28). Reflects wherever the previous point's
    # soft-stop happened to leave the rotor, not a controlled start.
    hal_bits, hal_state = _read_hal()
    if hal_state is not None:
        print(f"  Hall-Startposition: state={hal_state} (bits={hal_bits})")

    kickcount_before = _read_kickcount()

    # stdout/stderr captured separately, not merged -- same reasoning
    # as run_experiment.py's _run_motor_capture(): ssh's own banner
    # text must never end up mixed into the CSV.
    cmd = (f"cd /home/pi/auto && python3 capture_step_response.py "
           f"--p-delta {p} --i-delta {i}")
    result = subprocess.run(["ssh", PI_HOST, cmd], capture_output=True, text=True)
    csv_path.write_text(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return None, None, None

    kickcount_after = _read_kickcount()
    kicks = None
    if kickcount_before is not None and kickcount_after is not None:
        # mod-16 wraparound, see run_experiment.py's own comment --
        # not a concern within one ~7s point in practice.
        kicks = (kickcount_after - kickcount_before) % 16

    # capture_step_response.log rotates fresh on every invocation (one
    # generation kept) -- fetch it now, right after this point, or it's
    # gone once the next point overwrites it. watchdog.log is different
    # (continuously appended, never reset by capture_step_response.py),
    # so that one is fetched once at the very end instead, in main().
    log_path = run_dir / f"{name}.log"
    fetch = None
    for attempt in range(LOG_FETCH_RETRIES):
        fetch = subprocess.run(
            ["scp", f"{PI_HOST}:/home/pi/auto/capture_step_response.log", str(log_path)],
            capture_output=True, text=True)
        if fetch.returncode == 0:
            break
        time.sleep(1)
    else:
        print(f"WARNUNG: capture_step_response.log für {name} nicht abholbar "
              f"(3 Versuche): {fetch.stderr.strip()}")

    return csv_path, kicks, hal_state


def _read_rpm_series(csv_path):
    # Shared by _compute_ise()/_compute_mssd() -- (elapsed_seconds, rpm)
    # pairs, skipping the header and any blank/"None" rpm sample (same
    # skip both metrics need).
    series = []
    for line in csv_path.read_text().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            rpm = int(parts[1])
            t = int(parts[0]) / 1000
        except ValueError:
            continue
        series.append((t, rpm))
    return series


def _compute_ise(csv_path):
    return sum((TARGET_SPEED - rpm) ** 2 for _, rpm in _read_rpm_series(csv_path))


def _compute_mssd(csv_path, window_s=None):
    # Mean Square Successive Difference (von Neumann 1941) -- mean of
    # (rpm[i+1]-rpm[i])^2 over consecutive samples, independent of
    # distance from target (which ISE alone already covers). Squaring,
    # not just summing |diff| (the original 2026-08-25 "Total
    # Variation" version), matters in practice: a plain absolute-value
    # sum scores "one violent single reversal" the same as "many small
    # even wobbles" of similar total size, but a real P+0.10,I=0.00
    # trace (one sharp 900-then-crash-to-575 double-reversal early on)
    # sounded/looked clearly rougher than a P+0.10,I=-0.03 trace with a
    # similar absolute-sum TV but no single jump anywhere near that
    # large -- squaring, like ISE already does for target distance,
    # punishes the one big jolt disproportionately more and separates
    # the two clearly (roughly 2x apart squared vs ~14% apart linear).
    # Mean, not sum, so the 2s and full-window variants stay comparable
    # in magnitude despite covering a different number of samples. See
    # CLAUDE.md's Grid Search section for the real traces that prompted
    # this. window_s=None uses the whole capture; a numeric window_s
    # restricts to the first window_s seconds so steady-state ripple
    # (present in every point) doesn't drown out a rougher rise phase
    # specifically.
    series = _read_rpm_series(csv_path)
    if window_s is not None:
        series = [(t, rpm) for t, rpm in series if t <= window_s]
    diffs = [(b - a) ** 2 for (_, a), (_, b) in zip(series, series[1:])]
    return sum(diffs) / len(diffs) if diffs else 0.0


# How long rpm can plausibly stay at exactly 0 right after the step
# before it counts as suspicious -- modeled on the real 2026-08-22
# stiction/overshoot event (~800ms stuck at 0, then a jump to >2x
# target, see CLAUDE.md's Grid Search section and analysis/
# grid_search_log.md's 2026-08-22 entry). Every normal slow start seen
# since (including weak-P points, which start slower by design) has
# stayed well under this -- worst observed so far ~0.4s.
STICTION_STUCK_THRESHOLD_S = 0.6


def _detect_stiction(csv_path):
    # Returns how long (seconds) rpm stayed at exactly 0 from the very
    # start of the capture, if that exceeds STICTION_STUCK_THRESHOLD_S,
    # else None. Does not try to also confirm the "then a big jump"
    # half of the original event -- staying stuck unusually long is
    # already the anomalous, worth-a-repeat signal on its own, whether
    # or not a large overshoot follows it.
    series = _read_rpm_series(csv_path)
    if not series:
        return None
    stuck_until = None
    for t, rpm in series:
        if rpm == 0:
            stuck_until = t
        else:
            break
    if stuck_until is None or stuck_until < STICTION_STUCK_THRESHOLD_S:
        return None
    return stuck_until


def _report_stiction_warnings(run_dir, results):
    # Quick end-of-run sanity check -- see CLAUDE.md's Grid Search
    # section, 2026-08-25 discussion: narrowly scoped to the one
    # concrete, already-understood failure pattern (stuck-then-jump),
    # not a general "does this look statistically odd" judgment, which
    # would need thresholds this project doesn't have enough data to
    # set confidently yet.
    flagged = []
    for (p, i) in results:
        csv_path = run_dir / f"{_point_name(p, i)}.csv"
        if not csv_path.exists():
            continue
        stuck = _detect_stiction(csv_path)
        if stuck is not None:
            flagged.append((p, i, stuck))
    if flagged:
        print(f"\nWARNUNG: {len(flagged)} Punkt(e) zeigen ein Losbrech-/Stiction-Muster "
              f"(rpm blieb ungewöhnlich lange bei 0) -- ggf. wiederholen:")
        for p, i, stuck in flagged:
            print(f"  P delta={p:+.2f}, I delta={i:+.2f}: rpm blieb {stuck:.2f}s bei 0")
    else:
        print("\nKein Losbrech-/Stiction-Muster erkannt -- Lauf sieht unauffällig aus.")


def _print_matrix(results, p_values, i_values, key, label):
    print(f"\n{label} (Zeilen = I, hoechster Wert oben; Spalten = P, hoechster Wert rechts):")
    header = "          " + "".join(f"P={p:+.2f}    " for p in p_values)
    print(header)
    for i in reversed(i_values):
        row = f"I={i:+.2f}  "
        for p in p_values:
            point = results.get((p, i))
            val = point[key] if point is not None else None
            row += f"{val:11.0f}" if val is not None else "        n/a"
        print(row)


def _write_results_csv(results, out_path):
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["p_delta", "i_delta", "ise", "mssd_2s", "mssd_full", "kicks", "hal_state"])
        for (p, i), r in results.items():
            writer.writerow([p, i, r["ise"], r["mssd_2s"], r["mssd_full"], r.get("kicks"),
                              r.get("hal_state")])


def _make_best_point_plot(csv_path, out_path, p_delta, i_delta, ise):
    # LIN-only (no Saleae/Hall overlay -- the grid search doesn't use
    # it, see analysis/CLAUDE.md's Cost Function section), same
    # rpm-step + current-on-twin-axis style as run_experiment.py's
    # _make_plot() otherwise.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t, rpm = [], []
    cur_t, cur_val1, cur_val2 = [], [], []
    for line in csv_path.read_text().splitlines()[1:]:  # skip the CSV header
        parts = line.strip().split(",")
        if len(parts) != 4:
            continue
        elapsed_ms, rpm_s, val1, val2 = parts
        try:
            r = int(rpm_s)
        except ValueError:
            continue  # blank/"None" rpm field, same skip as _compute_ise()
        tt = int(elapsed_ms) / 1000
        t.append(tt)
        rpm.append(r)
        if val1 and val2:
            cur_t.append(tt)
            cur_val1.append(float(val1))
            cur_val2.append(float(val2))

    fig, ax1 = plt.subplots(figsize=(11, 6))
    l1, = ax1.step(t, rpm, where="mid", color="tab:blue", linewidth=1.5,
                    label="LIN st2mot `rpm`")
    ax1.set_xlabel("time since step [s]")
    ax1.set_ylabel("rpm")

    ax2 = ax1.twinx()
    l2, = ax2.plot(cur_t, cur_val1, color="tab:red", marker="s", markersize=5,
                    linewidth=1.2, label="current_val1 [A]")
    l3, = ax2.plot(cur_t, cur_val2, color="tab:purple", marker="^", markersize=5,
                    linewidth=1.2, label="current_val2 [A]")
    ax2.set_ylabel("current [A]")

    ax1.set_title(f"run_grid.py best point: P delta={p_delta:+.2f}, "
                  f"I delta={i_delta:+.2f}, ISE={ise:.0f}")
    ax1.legend(handles=[l1, l2, l3], loc="lower right", fontsize=9)
    ax1.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)


def _fetch_watchdog_log(run_dir):
    # watchdog.log covers the whole sweep -- continuously appended,
    # never reset between points, so one fetch at the end already has
    # everything (see CLAUDE.md's Grid Search section). Shared with
    # run_grid_row.py, which has the exact same one-fetch-at-the-end
    # need for its own 9-point row.
    watchdog_log = run_dir / "watchdog.log"
    fetch = None
    for attempt in range(LOG_FETCH_RETRIES):
        fetch = subprocess.run(
            ["scp", f"{PI_HOST}:/home/pi/auto/watchdog.log", str(watchdog_log)],
            capture_output=True, text=True)
        if fetch.returncode == 0:
            return
        time.sleep(1)
    print(f"WARNUNG: watchdog.log nicht abholbar (3 Versuche): {fetch.stderr.strip()}")


def _run_analyze_logs(run_dir):
    all_logs = sorted(str(p) for p in run_dir.glob("*.log"))
    if all_logs:
        print("\n--- analyze_logs.py ---")
        analyze = subprocess.run(
            [sys.executable, str(REPO_ROOT / "raspi" / "analyze_logs.py"), *all_logs]
        )
        if analyze.returncode != 0:
            print("WARNUNG: analyze_logs.py hat Auffälligkeiten gefunden, siehe oben.")
    else:
        print("WARNUNG: keine Logs abholbar, analyze_logs.py übersprungen.")


def main():
    print(CHECKLIST)
    _check_stm32_and_watchdog()
    if not _confirm("Checkliste erledigt, alles bereit (inkl. Hand an der Stromversorgung "
                     "für die ganze Runde)?"):
        sys.exit("Abgebrochen.")

    p_delta, i_delta = _get_deltas()
    p_values = [-p_delta, 0.0, p_delta]
    i_values = [-i_delta, 0.0, i_delta]

    if not _confirm(f"Motor jetzt für die ganze 3x3-Runde starten "
                     f"(P delta=±{p_delta}, I delta=±{i_delta})?"):
        sys.exit("Abgebrochen.")

    timestamp = time.strftime("%Y-%m-%d_%H%M%S")
    run_dir = REPO_ROOT / "runs" / f"{timestamp}_grid"
    run_dir.mkdir(parents=True, exist_ok=True)

    points = [(p, i) for i in i_values for p in p_values]
    results = {}
    aborted = False
    try:
        for idx, (p, i) in enumerate(points, start=1):
            csv_path, kicks, hal_state = _run_point(p, i, run_dir, idx, len(points))
            if csv_path is None:
                sys.exit(f"pi-Kommando abgelehnt oder SSH-Fehler bei "
                          f"P delta={p:+.2f}, I delta={i:+.2f} -- ganze Runde abgebrochen.")
            results[(p, i)] = {
                "ise": _compute_ise(csv_path),
                "mssd_2s": _compute_mssd(csv_path, window_s=MSSD_SHORT_WINDOW_S),
                "mssd_full": _compute_mssd(csv_path, window_s=None),
                "kicks": kicks,
                "hal_state": hal_state,
            }
            if idx < len(points):
                time.sleep(INTER_POINT_PAUSE_S)
    except KeyboardInterrupt:
        aborted = True
        print(f"\nABGEBROCHEN VOM USER nach Punkt {len(results)}/{len(points)}.")
        _send_speed_zero()

    _fetch_watchdog_log(run_dir)
    _run_analyze_logs(run_dir)

    if results:
        _write_results_csv(results, run_dir / "grid_results.csv")
        _print_matrix(results, p_values, i_values, "ise", "ISE-Matrix")
        _print_matrix(results, p_values, i_values, "mssd_2s",
                      f"MSSD-Matrix (erste {MSSD_SHORT_WINDOW_S:.0f}s)")
        _print_matrix(results, p_values, i_values, "mssd_full",
                      "MSSD-Matrix (gesamte 7s)")
        _print_matrix(results, p_values, i_values, "kicks",
                      "Kickstart-Zaehler (Anzahl Feuerungen, experimentelle Diagnose)")
        _print_matrix(results, p_values, i_values, "hal_state",
                      "Hall-Startposition (Zustand 0-5 vor dem Sprung, experimentelle Diagnose)")
        best = min(results, key=lambda k: results[k]["ise"])
        best_ise = results[best]["ise"]
        print(f"\nBester Punkt (nach ISE): P delta={best[0]:+.2f}, I delta={best[1]:+.2f}, "
              f"ISE={best_ise:.0f}")

        best_csv = run_dir / f"{_point_name(*best)}.csv"
        if best_csv.exists():
            plot_path = run_dir / f"best_{_point_name(*best)}.png"
            _make_best_point_plot(best_csv, plot_path, best[0], best[1], best_ise)
            print(f"Chart des besten Punkts: {plot_path}")

        _report_stiction_warnings(run_dir, results)

    if aborted:
        (run_dir / "ABORTED_BY_USER.txt").write_text(
            f"Abgebrochen nach {len(results)}/{len(points)} Punkten.\n"
        )

    print(f"\nErgebnisse in {run_dir}")
    if aborted:
        sys.exit(1)


if __name__ == "__main__":
    main()
