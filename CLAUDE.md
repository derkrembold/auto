# Auto — Automatisiertes BLDC-Motor-Test- und Optimierungstool

## Ziel

Autonome Optimierungsschleife für einen BLDC-Motor-Regelalgorithmus auf einem
STM32-Controller. Ein Parametersatz wird gebaut, geflasht, der Motor läuft ein
Testintervall, die Drehzahl wird gemessen, daraus werden Regelkennzahlen
berechnet, und der nächste Parametersatz wird davon abgeleitet.

## Beteiligte Rechner/Geräte

- **STM32-Rechner (Windows, dieser Rechner)**: Hier läuft Claude Code. Hier ist
  STM32CubeIDE/STM32_Programmer_CLI installiert, hier hängt auch der Saleae
  Logic Pro 16 dran.
- **STM32-Controller**: Führt den Regelalgorithmus aus, steuert den BLDC-Motor.
- **Raspberry Pi**: Reiner Ausführungsknoten ohne eigene KI. Sendet LIN-Bus-
  Kommandos (Start/Stop/Speed) an den Motor-Controller. Wird von Claude Code
  per SSH ferngesteuert (Skripte hochladen, ausführen, Ergebnis zurücklesen).
- **Saleae Logic Pro 16**: Zeichnet die 3 Hall-Sensor-Kanäle des Motors plus
  einen Trigger-Kanal auf. Übernimmt komplett die Drehzahlmessung — kein
  Rücklesen von Messdaten mehr über LIN.

## Datenfluss / Steuerkanäle

- **Steuerung (LIN, bereits implementiert):** Raspi → STM32-Controller.
  Kommandos: Motor Start, Motor Stop, Speed setzen.
- **Messung (Saleae, non-invasiv):** Die 3 Hall-Sensor-Signale werden ohnehin
  für die Kommutierung benötigt — der Saleae zapft sie nur ab, ohne dass die
  Firmware dafür geändert werden muss. Daraus wird per Software (Zeit zwischen
  Flankenwechseln) die Momentandrehzahl berechnet.
- **Trigger-Pin:** Ein zusätzlicher freier GPIO-Pin am STM32-Controller wird
  beim Start des Regelalgorithmus auf High gesetzt (direkt im Codepfad, der
  auch den Motorstart auslöst) und beim Stop wieder auf Low. Dieser Pin läuft
  als 4. Kanal mit in den Saleae-Capture und dient als Hardware-Trigger für
  den Aufnahmestart — keine Software-Synchronisation zwischen Systemen nötig.

## Sicherheit

- **Der Watchdog auf dem Raspi (`raspi/watchdog/`) ist unabhängig vom
  Optimierungs-Loop und von Claude Code.** Er läuft als eigener Prozess und
  stoppt den Motor selbstständig, wenn z. B. zu lange kein Lebenszeichen /
  Kommando ankommt. Grenzwerte (max. Speed etc.) gehören in den Code, nicht
  in Prompts oder Claude-seitige Disziplin.
- Ein manueller Not-Aus-Weg soll unabhängig vom Loop jederzeit auslösbar sein.

## Repo-Struktur

```
Auto/
├── STM32/          Firmware + Build/Flash-Automatisierung (STM32 CLI)
├── raspi/
│   ├── control/    LIN-Master-Code (Start/Stop/Speed) — bereits implementiert
│   └── watchdog/   Unabhängige Sicherheitsschranke, läuft getrennt vom Rest
├── saleae/
│   ├── capture_config/   Kanalbelegung, Trigger-Setup, Sample-Rate
│   └── exports/          Rohe Capture-Exporte pro Testlauf
├── analysis/       Drehzahlberechnung aus Hall-Flanken, Regelkennzahlen
└── runs/           Pro Iteration: Parametersatz, Rohdaten, Metriken
```

`raspi/*` wird hier im Repo entwickelt/versioniert, aber per SSH/SCP auf den
Raspi deployed — der Raspi selbst ist nur Ausführungsziel, kein Git-Checkout.

## Offene Punkte / noch zu klären

- Genaue Pin-Belegung (Hall-Kanäle, Trigger-Pin) — hier ergänzen, sobald fix.
- Saleae Sample-Rate für Hall-Kanäle.
- Kostenfunktion/Metrik-Gewichtung für die Optimierungsschleife.
- Deployment-Mechanismus Repo → Raspi (Skript noch zu bauen).
