# PROCESS

Wie Autor, Claude und Codex zusammenarbeiten. Verbindlich für alle drei.

## Die drei Ablagen

* Issues in GITHUB: [View 1 · Auto](https://github.com/users/derkrembold/projects/2)
* **`issues/`** — je Issue eine Markdown-Datei mit derselben Issue Nummer. Hier steht die Kommunikation: Befunde, Rückfragen, Entscheidungen, Ergebnis. Sie dient zur Agenten Kommunikation zwischen Codex und Claude.
* Subprojekte: STM32, raspi, currentsensor etc.

## Nummern

* Format der Markdown Datei: `I-0001`. Die Nummer in der Datei enthält die tatsächliche Issue-Nummer von GITHUB.
* Wenn ein Issue bearbeitet wird, aber es gibt noch kein md File, dann wird im issues/ dir ein neues angelegt. Diese Aufgabe wird generell Claude übernehmen.

## Issues in GITHUB

Claude oder Autor wird Issues in GITHUB anlegen. Codex wird, wenn überhaupt nötig, nur lesen auf Issues zugreifen. Es wird angenommen, dass zwischen Claude und Codex nur über die issues-dateien im issue dir kommuniziert wird.
**Grund**: die Kommunikation ist viel effizienter über shared files.

## Status — GITHUB ist die einzige Quelle der Wahrheit

Es gibt bewusst **keinen zweiten Status** in der issue-Datei, der mit GITHUB auseinanderlaufen könnte. GITHUB kennt nur drei Zustände (Board-Spalten `Todo` / `In Progress` / `Done`, plus offen/geschlossen am Issue selbst) — das reicht, weil "wartet auf Codex-Review" und "Claude bearbeitet gerade" beide einfach unter `In Progress` fallen. Die feinere Unterscheidung (ist Codex mit dem Review durch oder nicht) steht ausschließlich in der issue-Datei selbst, über das `review`-Feld — nicht in GITHUB.

## Die issue-Datei

Dateiname `issues/I-0007.md`, damit die Nummer im Dateibaum sichtbar ist.

```markdown
---
id: I-0007
titel: "Gleicher Titel wie in GITHUB"
review: offen
fuer: Claude
datum: 2026-09-28
betrifft: raspi
---

## Codex, 28.09.2026

Unter Bild 3 fehlt die Normangabe, die Unterschrift nennt nur den Titel.

## Ergebnis

```

Felder:

* `id` — die Nummer, gleich der in GITHUB
* `titel` — kurz, gleichlautend mit dem Issue Titel in GITHUB. **Immer in Anführungszeichen setzen.**
* `review` — `offen` oder `done`. Das einzige Statusfeld in dieser Datei, und Codex' einziges Schreibrecht auf das Frontmatter (siehe "Wer darf was"). Codex setzt `done`, sobald sein Durchlauf fertig ist — egal ob er etwas gefunden hat oder nicht.
* `fuer` — `Claude`, `Codex` oder `Autor`, wer als Nächstes am Zug ist. Nur eine Orientierungshilfe, nicht maßgeblich.
* `datum` — Anlagedatum
* `betrifft` — Pfad der betroffenen subprojekte. Darf mehrere Einträge haben.

Im Text je Beitrag eine Überschrift mit Name und Datum. Am Ende der Abschnitt `## Ergebnis` mit der Entscheidung. Auch ein verworfener Befund bekommt dort eine Begründung, damit nachvollziehbar bleibt, warum nichts geändert wurde.

## Ablauf

1. **Claude** arbeitet einen Punkt ab, setzt in GITHUB `In Progress`, und legt/aktualisiert die issue-Datei mit `review: offen`.
2. **Codex** prüft nur Punkte in der korrespondierenden issue-Datei in der issues dir. Er schreibt seine Befunde in die issue-Datei und setzt danach `review: done`. Findet er nichts, schreibt er das trotzdem in die issue-Datei und setzt `review: done` genauso. **Teil seiner Aufgabe ist auch, sinnvolle neue Testfälle vorzuschlagen** — insbesondere wenn eine Änderung Verhalten einführt oder umbenennt, das bisher nicht (oder nicht mehr korrekt) durch Tests abgedeckt ist. Ein Vorschlag reicht als Text in der issue-Datei, Codex schreibt selbst keine Testdateien (siehe "Wer darf was").
3. **Claude** sieht `review: done`, arbeitet die Befunde ab und bespricht sie mit dem **Autor**.
4. **Claude** trägt das `## Ergebnis` ein und schließt das issue in GITHUB (`In Progress` → `Done`), mit Absprache des Autors.

Ein Befund verschwindet damit nie, ohne dass der Autor ihn gesehen hat.

## Wer darf was

|        | GITHUB                            | issues/                                     | Skripte, Tabellen, Bilder | Commit und Push |
| ------ | --------------------------------- | -------------------------------------------- | ------------------------- | --------------- |
| Autor  | alles                             | alles                                        | alles                     | ja              |
| Claude | alles                             | alles                                        | alles                     | ja, nach Ansage |
| Codex  | lesen, vorallem Titel, und Status | Befunde schreiben, nur Feld `review` setzen  | **nichts**                | **nein**        |
