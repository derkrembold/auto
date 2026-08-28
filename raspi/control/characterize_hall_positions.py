"""Automatic Hall-position breakaway-threshold characterization: the
operator positions the rotor by hand only ONCE, at the very start, and
reads off which of the motor's 4 mechanical "quarters" (pole-pair
repetitions) that is from their own physical mark on the shaft/rotor --
the only way to know this at all, since the Hall sensors alone can only
resolve the 6 electrical states, not which of the 4 mechanical
repetitions is active (see root CLAUDE.md's LIN Protocol section and
analysis/grid_search_log.md's Dead Zone discussion, and that log's
2026-08-28 "kannst du das bestätigen?" discussion for why). From then
on, each successful escalating `pulse <value>` (cntl1mot, open-loop, no
PI/ramp -- see watchdog.py's PULSE_SPEED_MIN/MAX) that breaks the rotor
free into a new Hall sector IS the positioning for the next iteration --
no repositioning by hand needed between measurements (realized
2026-08-28: the operator had already observed live that a strong-enough
pulse, e.g. 1000, reliably drives the rotor forward, so the pulse that
characterizes one position can just as well BE the transport to the
next one). Runs fully unattended until QUARTER_STEPS (6) electrical
states have been crossed since the start -- i.e. exactly one quarter --
then, rather than stopping right there, continues for up to
BONUS_ATTEMPTS_AFTER_BOUNDARY (2) more positions specifically to catch
a mittelrast/tiefrast that sits right at or just past the boundary
(found live 2026-08-28 -- stopping exactly on the boundary would have
missed it). A normal (non-stuck) bonus-round transition is NOT written
to the CSV -- its estimated quarter is past the operator's anchor
point, not trustworthy "quarter N data" -- only a stuck result during
the bonus round is recorded. Quarter tracking after the first position
relies on accumulating each transition's step size, assumed never to
exceed 5 (never a full extra electrical revolution within one short
pulse) -- physically plausible, but NOT verifiable from hal data alone,
so keeping each unattended run to about one quarter (plus the small
bonus margin) bounds how far that unverified assumption has to hold
before the operator re-anchors by hand, same one-confirmed-unit-then-
stop spirit as run_grid_row.py's row consent model. Also stops (with a
clear report, not a silent guess) if a position fails to break through
by the ceiling -- nothing to advance to in that case.

Per position: reads `hal` as a reference, then fires the pulse at
escalating strength, re-reading `hal` after each one, until either the
Hall state permanently differs from the reference (a real sector
transition, not a spring-back into the same detent -- see the
2026-08-28 discussion in analysis/grid_search_log.md of cogging-torque
"Rast" positions the rotor snaps back into) or the ceiling is reached.
The escalation threshold itself is the quantitative measurement --
replaces an earlier, more subjective weit/mittel/wenig design (see git
history) once a single fixed pulse strength turned out unable to
distinguish "moved but sprang back exactly into place" from "barely
moved at all" -- both look identical from a bare hal reading, but the
threshold-search design doesn't need to tell them apart, it only needs
"still not permanently through" vs. "through."

Built 2026-08-28, made fully automatic the same day. Real hardware, not
a pytest test case -- see raspi/CLAUDE.md's Test Suite Policy. Falls
under Motor Execution Consent like any other motor command: one
checklist/consent covers the whole session (the operator stays
physically present the entire time even though the script now runs
unattended, hand on the power supply, ready to cut it -- same
reasoning as run_grid.py's whole-sweep consent, see root CLAUDE.md's
Grid Search section), not one prompt per pulse.

Direction (cw/ccw, prompted at startup, default cw) is a plain sign
flip applied to every pulse sent -- the escalation itself
(pulse_start/step/ceiling) is always given as a magnitude. Run the
whole thing twice, once per direction, for a full characterization --
this script does not chain both directions in one run.

Everything is logged: every single pulse/hal command+reply (including
every intermediate escalation step, not just the final threshold) goes
to characterize_hall_positions.log (rotated, one generation kept, see
logsetup.rotate_log()). CSV (position_index,direction,quarter,
hal_ref_bits,hal_ref_state,threshold_pulse,hal_new_bits,hal_new_state,
attempts,detent_type) written directly to a file by the script itself
(quarter is computed, not measured -- see the operator-anchored
tracking described above; default a timestamped name in the current
directory, overridable at the
startup prompt) -- deliberately not the "print CSV to stdout, caller
redirects" convention capture_step_response.py/etc. use, so a
crash/Ctrl-C mid-run still leaves every already-collected row on disk
(flushed after each one), not just whatever happened to reach a pipe.
detent_type is only asked/filled when the ceiling is hit without a
permanent transition (see _ask_detent_type()) -- empty on every normal
row.
threshold_pulse is empty if no transition happened by the ceiling.
"""
import csv
import logging
import re
import sys
import time
from datetime import datetime
from multiprocessing.connection import Client

import logsetup
from motorcontrol import SOCKET_ADDRESS

LOG_PATH = "characterize_hall_positions.log"
logger = logging.getLogger("characterize_hall_positions")

# Mirrors STM32/firmware/Core/Src/main.c's getState()/driveStep()
# if-chain exactly -- see run_grid.py's own copy of this table for the
# same mapping used on the Windows-host analysis side.
HALL_STATE_TABLE = {
    (1, 0, 0): 4,
    (1, 0, 1): 5,
    (0, 0, 1): 0,
    (0, 1, 1): 1,
    (0, 1, 0): 2,
    (1, 1, 0): 3,
}

HAL_RE = re.compile(r"data=\['(0x[0-9a-f]{2})', '(0x[0-9a-f]{2})', '(0x[0-9a-f]{2})'\]")

# Escalation defaults, chosen 2026-08-28 from live probing at one
# position: 16 (KICKSTART_SPEED itself) barely did anything, 600 was
# audible but produced no permanent movement, 1000 broke through and
# kept advancing the rotor -- which is exactly what makes the fully
# automatic chaining below possible. 750 start / 1100 ceiling brackets
# that observed range with margin on both sides; not yet validated at
# every position -- may need revisiting if a position doesn't break
# through by 1100 (the run stops and reports rather than assuming it
# never will).
PULSE_START_DEFAULT = 750
# 25, not 50 (2026-08-28) -- now that one run only covers one quarter
# (6 logical steps, see QUARTER_STEPS below) instead of a full 24-step
# sweep, the finer resolution costs proportionally less total run time.
PULSE_STEP_DEFAULT = 25
PULSE_CEILING_DEFAULT = 1100
SETTLE_S = 0.5  # pause between a pulse and reading `hal` back -- needs
# to cover the mechanical settle/re-detent (cogging "Rast") too, not
# just the electrical pulse itself (2026-08-28, raised from 0.3s)

# One run now characterizes exactly one mechanical "quarter" (one of
# the motor's 4 pole-pair repetitions), not a fixed position count --
# see the 2026-08-28 discussion in analysis/grid_search_log.md: without
# an absolute position reference, only the OPERATOR (via a physical
# mark on the shaft, watched by eye) can reliably say which quarter a
# given Hall state instance belongs to. The script trusts that mark
# only at the start (see _ask_quarter() below); everything after that
# is inferred by accumulating each transition's step size (assumed
# never >5, i.e. never a full extra electrical revolution in one
# pulse -- physically plausible given how short a single pulse is, but
# NOT provable from hal data alone, see that discussion). Stopping at
# a quarter boundary (rather than continuing blindly through several)
# keeps that unverified assumption's reach short and gives the
# operator a natural, frequent checkpoint to re-anchor by hand, same
# spirit as run_grid_row.py's one-row-then-stop consent model.
QUARTER_STEPS = 6
NUM_POSITIONS_SAFETY_MAX = 24  # hard stop if quarter-crossing somehow never happens

# Found live 2026-08-28: a mittelrast can sit right at/just past a
# quarter boundary -- stopping the instant the boundary is crossed
# would miss it. So the run continues up to BONUS_ATTEMPTS_AFTER_
# BOUNDARY more positions past the boundary, purely to give a
# just-past-the-boundary mittelrast a chance to show up. A normal
# (non-stuck) bonus-round transition is deliberately NOT written to
# the CSV -- its estimated quarter is unverified (past the operator's
# anchor point), so it isn't trustworthy "quarter N data." A stuck
# (mittelrast/tiefrast) bonus-round result IS written, quarter and
# all, since catching that is the entire point of continuing.
BONUS_ATTEMPTS_AFTER_BOUNDARY = 2

CHECKLIST = """
Physische Vorbereitung:
  - Motor-Stromversorgung/Batterie an.
  - Du bleibst fuer die GANZE Charakterisierungs-Sitzung koerperlich
    anwesend, Hand an der Stromversorgung, bereit sofort abzuschalten --
    das deckt die Einwilligung fuer die ganze automatische Sequenz ab
    (siehe root CLAUDE.md's Grid Search Sektion), nicht ein einzelner
    Software-Prompt. Der Lauf ist unbeaufsichtigt, nicht unbeobachtet.
  - Du positionierst den Rotor nur EIN EINZIGES MAL, vor dem Start --
    danach uebernimmt jeder erfolgreiche Puls selbst den Transport zur
    naechsten Position, es wird zwischendurch nicht mehr nachgefragt.
  - Lies dabei an deiner eigenen Markierung am Rotor/Welle ab, in
    welchem der 4 Quartale du gerade stehst (0-3) -- das wird gleich
    abgefragt, und ist die einzige Quelle dafuer, welches der 4
    mechanisch gleich aussehenden Vorkommen eines Hall-Zustands das
    hier gerade ist.
(Watchdog laeuft --live wird nicht automatisch geprueft -- falls "pi"/
"pulse" mit ERR antwortet, ist er entweder nicht --live oder lehnt den
Wert ab.)
"""


def _send(conn, command):
    logger.info(f"-> {command}")
    conn.send(command)
    reply = conn.recv()
    logger.info(f"<- {reply}")
    return reply


def _read_hal(conn):
    reply = _send(conn, "hal")
    if not reply.startswith("OK"):
        return None, None, reply
    # reply looks like "OK ret=0 data=['0x01', '0x00', '0x00']"
    match = HAL_RE.search(reply)
    if not match:
        return None, None, reply
    bits = tuple(int(b, 16) for b in match.groups())
    return bits, HALL_STATE_TABLE.get(bits), reply


def _find_threshold(conn, pulse_start, pulse_step, pulse_ceiling, direction):
    # direction: +1 or -1, multiplied into every pulse sent -- the
    # escalation itself (pulse_start/step/ceiling) is always given as a
    # magnitude, direction decides which way it actually drives the
    # rotor (see driveStep()/driveState()'s own speed-sign convention
    # in main.c: positive = CW, negative = CCW). Returns (hal_ref_bits,
    # hal_ref_state, signed_threshold_or_None, hal_new_bits,
    # hal_new_state, attempts). threshold is None if no permanent
    # transition happened by pulse_ceiling -- hal_new_* then just
    # echoes hal_ref_* back, since nothing actually changed.
    hal_ref_bits, hal_ref_state, reply = _read_hal(conn)
    if hal_ref_bits is None:
        return None, None, None, None, None, 0

    attempts = 0
    pulse_magnitude = pulse_start
    while pulse_magnitude <= pulse_ceiling:
        attempts += 1
        signed_pulse = direction * pulse_magnitude
        pulse_reply = _send(conn, f"pulse {signed_pulse}")
        if not pulse_reply.startswith("OK"):
            print(f"WARNUNG: pulse {signed_pulse} abgelehnt ({pulse_reply}).")
            break
        time.sleep(SETTLE_S)
        hal_bits, hal_state, reply = _read_hal(conn)
        if hal_bits is None:
            print(f"WARNUNG: hal-Read nach pulse {signed_pulse} fehlgeschlagen ({reply}).")
            break
        print(f"    pulse={signed_pulse}: hal state={hal_state} (bits={hal_bits})")
        if hal_bits != hal_ref_bits:
            return hal_ref_bits, hal_ref_state, signed_pulse, hal_bits, hal_state, attempts
        pulse_magnitude += pulse_step

    return hal_ref_bits, hal_ref_state, None, hal_ref_bits, hal_ref_state, attempts


DETENT_TYPE_OPTIONS = ("mittelrast", "tiefrast")


def _ask_detent_type():
    # Only reached once the ceiling is hit without a permanent Hall
    # transition (run() below) -- the operator's live judgment of
    # whether this felt like a shallow detent the pulse just couldn't
    # push through in the right direction ("Mittelrast" -- see the
    # 2026-08-28 discussion in analysis/grid_search_log.md: easy by
    # hand, but the pulse's torque direction may be poorly aligned at
    # this exact rotor angle) or a genuinely deep/strong one
    # ("Tiefrast"). Not distinguishable from the hal/attempts data
    # alone, hence asked here rather than inferred.
    while True:
        answer = input(f"Rastentyp an dieser Stelle? ({'/'.join(DETENT_TYPE_OPTIONS)}): ").strip().lower()
        if answer in DETENT_TYPE_OPTIONS:
            return answer
        print(f"Bitte eines von: {', '.join(DETENT_TYPE_OPTIONS)}")


def _step_size(hal_ref_state, hal_new_state, direction):
    # Same convention as analysis/plot_hall_characterization.py's own
    # copy of this -- electrical states cycle 0..5, direction decides
    # which way "next" means. 0 if no permanent transition happened.
    if hal_new_state is None or hal_new_state == hal_ref_state:
        return 0
    return (hal_new_state - hal_ref_state) % 6 if direction == 1 else (hal_ref_state - hal_new_state) % 6


def run(csv_path, start_quarter, direction=1, pulse_start=PULSE_START_DEFAULT,
        pulse_step=PULSE_STEP_DEFAULT, pulse_ceiling=PULSE_CEILING_DEFAULT,
        address=SOCKET_ADDRESS):
    logsetup.configure("characterize_hall_positions", LOG_PATH, terminal_level=None)

    aborted = False
    cumulative_steps = 0  # since the start of this run, see QUARTER_STEPS above
    with open(csv_path, "w", newline="") as f, Client(address, family='AF_UNIX') as conn:
        writer = csv.writer(f)
        writer.writerow(["position_index", "direction", "quarter", "hal_ref_bits", "hal_ref_state",
                          "threshold_pulse", "hal_new_bits", "hal_new_state", "attempts",
                          "detent_type"])
        f.flush()

        _send(conn, "speed 0")  # known-rest baseline before any pulse
        print(f"Läuft automatisch bis ein Quartal (6 Zustände) durchlaufen ist, Richtung "
              f"{'CW (+)' if direction > 0 else 'CCW (-)'}, Startquartal {start_quarter}. "
              f"Ergebnisse werden laufend nach {csv_path} geschrieben.\n")

        quarter_left = False
        bonus_used = 0
        try:
            for index in range(1, NUM_POSITIONS_SAFETY_MAX + 1):
                quarter = (start_quarter + cumulative_steps // QUARTER_STEPS) % 4
                tag = " [Bonusversuch nach Quartalsgrenze]" if quarter_left else ""
                print(f"Position {index} (Quartal {quarter}){tag}:")
                (hal_ref_bits, hal_ref_state, threshold,
                 hal_new_bits, hal_new_state, attempts) = _find_threshold(
                    conn, pulse_start, pulse_step, pulse_ceiling, direction)

                if hal_ref_bits is None:
                    print("WARNUNG: hal-Read fehlgeschlagen -- Lauf wird abgebrochen.")
                    aborted = True
                    break

                if threshold is None:
                    # Stuck/mittelrast -- always recorded, bonus round or
                    # not, since catching exactly this near a boundary is
                    # why the bonus round exists at all.
                    print(f"  Kein dauerhafter Wechsel bis {pulse_ceiling} ({attempts} "
                          f"Versuche) -- keine Position zum Weitermachen, Lauf gestoppt.")
                    print(f"  Aktuelle Hall-Position: state={hal_ref_state} (bits={hal_ref_bits})")
                    detent_type = _ask_detent_type()
                    writer.writerow([index, direction, quarter, hal_ref_bits, hal_ref_state, "",
                                      hal_new_bits, hal_new_state, attempts, detent_type])
                    f.flush()
                    aborted = True
                    break

                print(f"  Durchbruch bei pulse={threshold} "
                      f"(state {hal_ref_state} -> {hal_new_state}, {attempts} Versuche)")
                if not quarter_left:
                    writer.writerow([index, direction, quarter, hal_ref_bits, hal_ref_state,
                                      threshold, hal_new_bits, hal_new_state, attempts, ""])
                    f.flush()  # a crash/Ctrl-C mid-run must not lose already-collected rows
                else:
                    bonus_used += 1
                    print(f"  (Bonusversuch {bonus_used}/{BONUS_ATTEMPTS_AFTER_BOUNDARY} nach "
                          f"der Quartalsgrenze, kein Mittelrast -- nicht in die CSV geschrieben.)")

                cumulative_steps += _step_size(hal_ref_state, hal_new_state, direction)

                if not quarter_left and cumulative_steps >= QUARTER_STEPS:
                    quarter_left = True
                    print(f"\nQuartal ({QUARTER_STEPS} Zustände) durchlaufen -- läuft noch bis zu "
                          f"{BONUS_ATTEMPTS_AFTER_BOUNDARY} Bonusversuche weiter, um einen "
                          f"Mittelrast direkt an der Grenze nicht zu verpassen.")
                elif quarter_left and bonus_used >= BONUS_ATTEMPTS_AFTER_BOUNDARY:
                    print(f"\n{BONUS_ATTEMPTS_AFTER_BOUNDARY} Bonusversuche nach der Quartalsgrenze "
                          f"ohne Mittelrast -- Lauf beendet.")
                    break
            else:
                print(f"\nWARNUNG: {NUM_POSITIONS_SAFETY_MAX} Positionen ohne Laufende -- "
                      f"Sicherheitsstopp, das sollte normalerweise nicht passieren.")
                aborted = True
        except KeyboardInterrupt:
            print("\nABGEBROCHEN VOM USER.")
            aborted = True

        _send(conn, "speed 0")  # belt-and-suspenders, matches every other script here

    print(f"\n{'Abgebrochen' if aborted else 'Fertig'}. Ergebnisse in {csv_path}")


if __name__ == "__main__":
    print(CHECKLIST)
    if input("Checkliste erledigt, Rotor einmal positioniert, alles bereit? [y/N]: ").strip().lower() != "y":
        sys.exit("Abgebrochen.")

    def _ask_int(prompt, default):
        raw = input(f"{prompt} (Enter = {default}): ").strip()
        return int(raw) if raw else default

    while True:
        raw_dir = input("Drehrichtung (cw/ccw, Enter = cw): ").strip().lower() or "cw"
        if raw_dir in ("cw", "ccw"):
            direction = 1 if raw_dir == "cw" else -1
            break
        print("Bitte 'cw' oder 'ccw' eingeben.")

    while True:
        raw_quarter = input("Startquartal (0-3, an der eigenen Markierung am Rotor abgelesen): ").strip()
        try:
            start_quarter = int(raw_quarter)
        except ValueError:
            print("Bitte eine Ganzzahl 0-3 eingeben.")
            continue
        if 0 <= start_quarter <= 3:
            break
        print("Bitte eine Ganzzahl 0-3 eingeben.")

    try:
        pulse_start = _ask_int("Start-Pulsstärke", PULSE_START_DEFAULT)
        pulse_step = _ask_int("Schrittweite", PULSE_STEP_DEFAULT)
        pulse_ceiling = _ask_int("Obergrenze", PULSE_CEILING_DEFAULT)
    except ValueError:
        sys.exit("Werte müssen Ganzzahlen sein.")

    default_csv = f"characterize_hall_positions_{raw_dir}_q{start_quarter}_{datetime.now():%Y-%m-%d_%H%M%S}.csv"
    csv_path = input(f"CSV-Ausgabedatei (Enter = '{default_csv}'): ").strip() or default_csv

    if input(f"Automatischer Lauf über ein Quartal, Richtung {raw_dir}, Startquartal "
             f"{start_quarter}, eskalierende Pulse {pulse_start}..{pulse_ceiling} "
             f"(Schritt {pulse_step}), jetzt starten? [y/N]: ").strip().lower() != "y":
        sys.exit("Abgebrochen.")
    run(csv_path, start_quarter, direction, pulse_start, pulse_step, pulse_ceiling)
