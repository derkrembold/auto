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
per point -> one results directory for the whole sweep, not one per
point -> 3x3 ISE matrix + grid_results.csv.

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


def _ssh_check(cmd):
    return subprocess.run(["ssh", PI_HOST, cmd], capture_output=True, text=True)


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


def _run_point(p, i, run_dir, index, total):
    print(f"\nPunkt {index}/{total}: P delta={p:+.2f}, I delta={i:+.2f}")
    name = _point_name(p, i)
    csv_path = run_dir / f"{name}.csv"

    # stdout/stderr captured separately, not merged -- same reasoning
    # as run_experiment.py's _run_motor_capture(): ssh's own banner
    # text must never end up mixed into the CSV.
    cmd = (f"cd /home/pi/auto && python3 capture_step_response.py "
           f"--p-delta {p} --i-delta {i}")
    result = subprocess.run(["ssh", PI_HOST, cmd], capture_output=True, text=True)
    csv_path.write_text(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return None

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

    return csv_path


def _compute_ise(csv_path):
    total = 0.0
    lines = csv_path.read_text().splitlines()
    for line in lines[1:]:  # skip the "elapsed_ms,rpm,..." header
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            rpm = int(parts[1])
        except ValueError:
            continue  # blank/"None" rpm field -- no reading that sample
        total += (TARGET_SPEED - rpm) ** 2
    return total


def _print_matrix(results, p_values, i_values):
    print("\nISE-Matrix (Zeilen = I, hoechster Wert oben; Spalten = P, hoechster Wert rechts):")
    header = "          " + "".join(f"P={p:+.2f}    " for p in p_values)
    print(header)
    for i in reversed(i_values):
        row = f"I={i:+.2f}  "
        for p in p_values:
            ise = results.get((p, i))
            row += f"{ise:11.0f}" if ise is not None else "        n/a"
        print(row)


def _write_results_csv(results, out_path):
    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["p_delta", "i_delta", "ise"])
        for (p, i), ise in results.items():
            writer.writerow([p, i, ise])


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
            csv_path = _run_point(p, i, run_dir, idx, len(points))
            if csv_path is None:
                sys.exit(f"pi-Kommando abgelehnt oder SSH-Fehler bei "
                          f"P delta={p:+.2f}, I delta={i:+.2f} -- ganze Runde abgebrochen.")
            results[(p, i)] = _compute_ise(csv_path)
            if idx < len(points):
                time.sleep(INTER_POINT_PAUSE_S)
    except KeyboardInterrupt:
        aborted = True
        print(f"\nABGEBROCHEN VOM USER nach Punkt {len(results)}/{len(points)}.")
        _send_speed_zero()

    # watchdog.log covers the whole sweep -- continuously appended,
    # never reset between points, so one fetch at the end already has
    # everything (see CLAUDE.md's Grid Search section).
    watchdog_log = run_dir / "watchdog.log"
    fetch = None
    for attempt in range(LOG_FETCH_RETRIES):
        fetch = subprocess.run(
            ["scp", f"{PI_HOST}:/home/pi/auto/watchdog.log", str(watchdog_log)],
            capture_output=True, text=True)
        if fetch.returncode == 0:
            break
        time.sleep(1)
    else:
        print(f"WARNUNG: watchdog.log nicht abholbar (3 Versuche): {fetch.stderr.strip()}")

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

    if results:
        _write_results_csv(results, run_dir / "grid_results.csv")
        _print_matrix(results, p_values, i_values)
        best = min(results, key=results.get)
        best_ise = results[best]
        print(f"\nBester Punkt: P delta={best[0]:+.2f}, I delta={best[1]:+.2f}, "
              f"ISE={best_ise:.0f}")

        best_csv = run_dir / f"{_point_name(*best)}.csv"
        if best_csv.exists():
            plot_path = run_dir / f"best_{_point_name(*best)}.png"
            _make_best_point_plot(best_csv, plot_path, best[0], best[1], best_ise)
            print(f"Chart des besten Punkts: {plot_path}")

    if aborted:
        (run_dir / "ABORTED_BY_USER.txt").write_text(
            f"Abgebrochen nach {len(results)}/{len(points)} Punkten.\n"
        )

    print(f"\nErgebnisse in {run_dir}")
    if aborted:
        sys.exit(1)


if __name__ == "__main__":
    main()
