#!/usr/bin/env python3
"""P/I row search: one line of 9 points along a single axis (P or I),
the other axis held fixed -- a sibling to run_grid.py's 3x3 stencil,
built for wider/finer coverage of one axis than a 3x3 grid gives in a
single invocation. Reuses run_grid.py's SSH/point-execution/ISE/MSSD
machinery directly (imported as a module, not duplicated).

Full design writeup lives in root CLAUDE.md's "Grid Search" and
"Candidate Selection Philosophy" sections -- read those for the
reasoning behind every decision below, this docstring only summarizes
the mechanics.

Physical checklist -> one motor-start consent covering the whole
9-point row (same reasoning as run_grid.py: the user stays physically
present with a hand on the power supply for the whole row) -> 9 points
evenly spaced on one axis around delta=0 (-4*step, -3*step, ..., 0,
..., +4*step), the other axis held at a fixed value -> capture_step_
response.py per point over SSH, no Saleae (see analysis/CLAUDE.md's
Cost Function section) -> ISE + MSSD per point -> one results
directory for the row -> grid_results.csv (same column schema as
run_grid.py's, so analysis/grid_heatmap.py can merge rows and grids
together later) + best-point chart.

Deliberately ONE row per invocation, no automated chaining across
rows -- once this row finishes, the script exits. For another row
(e.g. a different fixed value), run this again manually, with a fresh
consent, per the user's explicit design (2026-08-25): "Ein Bestätigung
ist ein 9 Punkte lauf. Dann wird beendet. Dann starte ich run_grid_row
von neu."

Usage:
    python3 run_grid_row.py <axis> <fixed_value> <step>

axis: "p" or "i" -- which one varies over the 9 points.
fixed_value: the delta held constant for the OTHER axis.
step: spacing between the 9 points on the varying axis.

Prompted interactively if not given as positional args.

P delta safety cap -- P_DELTA_MAX_DEFAULT (0.10): unlike the wire-level
range (left entirely to the watchdog's own validate(), deliberately not
duplicated here, same as run_grid.py), this cap is tool-specific policy
the watchdog has no way to know about -- it's where audible motor
roughness ("Ruppeln") was first found (see CLAUDE.md's Grid Search
section, 2026-08-25), not a hardware/protocol limit. So it IS checked
here, client-side, before anything runs -- a named, overridable
constant (not a hardcoded rule), since it may need to change later
(e.g. once tested under load), but defaults to enforcing today's
known-safe boundary. Applies to every point's P value in the row,
whether P is the row's fixed or its varying axis.
"""
import sys
import time

import run_grid as rg

# See this file's own docstring for why this is checked here (client
# side) rather than left to the watchdog, unlike the wire-level range.
P_DELTA_MAX_DEFAULT = 0.10

CHECKLIST = """
Physische Vorbereitung:
  - Motor-Stromversorgung/Batterie an.
  - Du bleibst fuer die GANZE 9-Punkte-Zeile koerperlich anwesend, Hand
    an der Stromversorgung, bereit sofort abzuschalten -- das deckt die
    Einwilligung fuer alle 9 Punkte ab (siehe CLAUDE.md's Grid Search
    Sektion), nicht ein einzelner Software-Prompt. Diese eine Zeile ist
    der ganze Lauf -- fuer eine weitere Zeile (z.B. anderer Fixwert)
    startest du run_grid_row.py danach manuell neu, mit frischer
    Zustimmung.
(STM32 laeuft und Watchdog laeuft --live werden unten automatisch
geprueft.)
"""


def _get_row_params():
    if len(sys.argv) == 4:
        axis = sys.argv[1].strip().lower()
        try:
            fixed_value = float(sys.argv[2])
            step = float(sys.argv[3])
        except ValueError:
            sys.exit("fixed_value/step müssen Zahlen sein.")
    else:
        while True:
            axis = input("Achse, die variiert (p/i): ").strip().lower()
            if axis in ("p", "i"):
                break
            print("Bitte 'p' oder 'i' eingeben.")
        other = "I" if axis == "p" else "P"
        while True:
            try:
                fixed_value = float(input(f"Fester Wert für {other} delta: ").strip())
                step = float(input("Schrittweite für die variierende Achse: ").strip())
                break
            except ValueError:
                print("Bitte eine Zahl eingeben.")
    if axis not in ("p", "i"):
        sys.exit("Achse muss 'p' oder 'i' sein.")
    return axis, fixed_value, abs(step)


def _row_points(axis, fixed_value, step):
    # 9 points, symmetric around delta=0 (the firmware default),
    # matching run_grid.py's same "0 = current default" convention.
    varying = [n * step for n in range(-4, 5)]
    if axis == "p":
        return [(v, fixed_value) for v in varying]
    return [(fixed_value, v) for v in varying]


def _check_p_delta_cap(points, limit):
    over = [p for p, i in points if abs(p) > limit + 1e-9]
    if over:
        worst = max(over, key=abs)
        sys.exit(f"P delta {worst:+.3f} überschreitet die Sicherheitsgrenze ±{limit} "
                  f"(P_DELTA_MAX_DEFAULT in run_grid_row.py) -- Abbruch vor jeder "
                  f"Motorbewegung. Grenze bewusst in der Konstante anpassen, falls nötig.")


def _print_row(results, points, key, label):
    print(f"\n{label}:")
    for p, i in points:
        val = results.get((p, i), {}).get(key)
        print(f"  P delta={p:+.3f}, I delta={i:+.3f}:  " +
              (f"{val:.0f}" if val is not None else "n/a"))


def main():
    axis, fixed_value, step = _get_row_params()
    points = _row_points(axis, fixed_value, step)
    _check_p_delta_cap(points, P_DELTA_MAX_DEFAULT)

    varying_label = "P" if axis == "p" else "I"
    fixed_label = "I" if axis == "p" else "P"
    varying_values = [p if axis == "p" else i for p, i in points]

    print(CHECKLIST)
    rg._check_stm32_and_watchdog()
    if not rg._confirm("Checkliste erledigt, alles bereit (inkl. Hand an der "
                        "Stromversorgung für die ganze Zeile)?"):
        sys.exit("Abgebrochen.")

    print(f"\nZeile: {varying_label} delta läuft {varying_values[0]:+.3f}.."
          f"{varying_values[-1]:+.3f} in {step}er-Schritten, "
          f"{fixed_label} delta fest bei {fixed_value:+.3f}")
    if not rg._confirm("Motor jetzt für die ganze 9-Punkte-Zeile starten?"):
        sys.exit("Abgebrochen.")

    timestamp = time.strftime("%Y-%m-%d_%H%M%S")
    run_dir = rg.REPO_ROOT / "runs" / f"{timestamp}_row"
    run_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    aborted = False
    try:
        for idx, (p, i) in enumerate(points, start=1):
            csv_path, kicks = rg._run_point(p, i, run_dir, idx, len(points))
            if csv_path is None:
                sys.exit(f"pi-Kommando abgelehnt oder SSH-Fehler bei "
                          f"P delta={p:+.2f}, I delta={i:+.2f} -- ganze Zeile abgebrochen.")
            results[(p, i)] = {
                "ise": rg._compute_ise(csv_path),
                "mssd_2s": rg._compute_mssd(csv_path, window_s=rg.MSSD_SHORT_WINDOW_S),
                "mssd_full": rg._compute_mssd(csv_path, window_s=None),
                "kicks": kicks,
            }
            if idx < len(points):
                time.sleep(rg.INTER_POINT_PAUSE_S)
    except KeyboardInterrupt:
        aborted = True
        print(f"\nABGEBROCHEN VOM USER nach Punkt {len(results)}/{len(points)}.")
        rg._send_speed_zero()

    rg._fetch_watchdog_log(run_dir)
    rg._run_analyze_logs(run_dir)

    if results:
        rg._write_results_csv(results, run_dir / "grid_results.csv")
        _print_row(results, points, "ise", "ISE")
        _print_row(results, points, "mssd_2s",
                   f"MSSD (erste {rg.MSSD_SHORT_WINDOW_S:.0f}s)")
        _print_row(results, points, "mssd_full", "MSSD (gesamte 7s)")
        _print_row(results, points, "kicks",
                   "Kickstart-Zaehler (Anzahl Feuerungen, experimentelle Diagnose)")

        best = min(results, key=lambda k: results[k]["ise"])
        best_ise = results[best]["ise"]
        print(f"\nBester Punkt (nach ISE): P delta={best[0]:+.2f}, I delta={best[1]:+.2f}, "
              f"ISE={best_ise:.0f}")

        best_csv = run_dir / f"{rg._point_name(*best)}.csv"
        if best_csv.exists():
            plot_path = run_dir / f"best_{rg._point_name(*best)}.png"
            rg._make_best_point_plot(best_csv, plot_path, best[0], best[1], best_ise)
            print(f"Chart des besten Punkts: {plot_path}")

        rg._report_stiction_warnings(run_dir, results)

    if aborted:
        (run_dir / "ABORTED_BY_USER.txt").write_text(
            f"Abgebrochen nach {len(results)}/{len(points)} Punkten.\n"
        )

    print(f"\nErgebnisse in {run_dir}")
    if aborted:
        sys.exit(1)


if __name__ == "__main__":
    main()
