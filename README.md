Inhalt

1. [01Systemüberblick](#ueberblick)
2. [02Sicherheitskonzept](#sicherheit)
3. [03LIN-Bus & Adressen](#lin)
4. [04Watchdog](#watchdog)
5. [05Bedien-Clients](#clients)
6. [06Mess- & Testskripte](#messung)
7. [07STM32-Firmware](#firmware)
8. [08Sensor-Slaves](#sensoren)
9. [09Optimierung & Analyse](#optimierung)
10. [10Werkzeuge & Prozess](#werkzeuge)
11. [11Typische Abläufe](#rezepte)
12. [12Offene Punkte](#offen)

Repo `auto` · Stand 7. Oktober 2026

# Auto Systemhandbuch

Ein Raspberry Pi steuert über LIN-Bus zwei STM32-Motorcontroller für Bosch-BLDC-Motoren (1000 W). Ein unabhängiger Watchdog überwacht Drehzahl und Strom, ein Joystick fährt das Fahrzeug, und auf dem Windows-Rechner laufen Firmware-Build, Saleae-Messungen und die P/I-Parametersuche. Diese Seite erklärt jede Komponente, wie sie zusammenspielen und wie du sie benutzt.

gebaut & auf Hardware bestätigt gebaut, Hardware-Test offen geplant LIN 19 200 Bd STM32H743 · ATmega328P · Pi

01

## Systemüberblick

Drei Rechner, ein Bus. Der Windows-Host baut und flasht Firmware und wertet Messungen aus. Der Pi ist reiner Ausführungsknoten ohne eigene KI: Er bekommt Skripte per SCP und wird per SSH gesteuert. Auf dem LIN-Bus spricht nur einer aktiv, nämlich der Watchdog-Prozess auf dem Pi.

Durchgezogene Petrol-Linie: LIN-Bus (Pi ist Master, alle anderen Slaves). Gestrichelt Kupfer: reiner Mess-Abgriff der Hall-Signale, keine Steuerverbindung. Firmware wird separat per ST-Link (SWD) vom Windows-Host geflasht.

### Die Komponenten auf einen Blick

| Ordner | Läuft auf | Aufgabe | Status |
| --- | --- | --- | --- |
| raspi/watchdog/ | Pi | Sicherheitsbarriere und einziger LIN-Master (`watchdog.py`, `linbus.py`) | bestätigt |
| raspi/control/ | Pi | Clients: Kommando-CLI, Joystick, Sprungantwort, Validierungen, Stresstest | bestätigt |
| raspi/tests/ | Windows/Pi | pytest-Suite gegen DryRunLin und Mocks, keine Hardware | grün |
| STM32/firmware/ | STM32H743 | Kommutierung, PI-Regler, Kickstart, LIN-Slave | bestätigt |
| currentsensor/ | ATmega328P | LIN-Slave, zwei Stromkanäle, Fehler-Ringpuffer | bestätigt |
| lightsensor/ | ATmega328P | Kursprojekt-Fragmente, baut, noch nicht am Bus | geplant |
| run\_\*.py | Windows | Ein Messpunkt, 3×3-Gitter, 9-Punkt-Reihe für die P/I-Suche | abgeschlossen |
| analysis/ | Windows | Hall-Flanken → rpm, Heatmaps, Hall-Charakterisierung | bestätigt |
| saleae_mcp/ | Windows | MCP-Server um die Saleae-Automation-API | bestätigt |
| addresses.json | Windows | Einzige Quelle für alle LIN-PIDs, erzeugt Python- und C-Tabellen | aktiv |

### Ein Befehl auf seinem Weg

Am Beispiel `speed 0 500` (Motor 0 auf 500 rpm):

**1 · Client**motorcontrol.py oder joystick.py schickt den Text über den Unix-Socket

→

**2 · validate()**Verb bekannt? Instanz 0–3? Wert in ±3000?

→

**3 · Lock**Kein gleichzeitiger Bus-Zugriff mit dem Poll-Thread

→

**4 · linbus**Frame `55 4C 01 F4 09`, jedes Byte mit Echo-Vergleich

→

**5 · STM32**ISR erkennt PID, Checksumme OK → `controlvariableinput = 500`

→

**6 · Regelung**PI-Regler und Kommutierung drehen den Motor; Trigger-Pin geht HIGH

02

## Sicherheitskonzept

Grenzen stehen im Code, nicht in Prompts. Mehrere Schichten fangen unterschiedliche Fehler ab, und jede kann den Motor ohne die anderen stoppen. Bei einem Fehler an einem Motor stoppt der Watchdog immer *alle* bekannten Motoren, weil ein einseitig weiterfahrendes Differentialfahrzeug sich drehen oder ruckeln würde.

| Schicht | Erkennt | Reaktion | Zeit |
| --- | --- | --- | --- |
| Firmware: Kickstart-Abbruch | Sollwert ≠ 0, aber 7 × 100 ms lang rpm = 0 | Sollwert und Integral auf 0, `sysError = −65` (STALL_TIM_ERR) | \~0,7 s |
| Firmware: Checksummen-Gate | Beschädigter Master-Write | Befehl wird verworfen, Zähler steigt | sofort |
| Firmware: UART-Fehler-Callback | Overrun/Framing-Fehler auf dem Bus | Empfang neu scharf, Sollwert 0, `sysError = −8` | sofort |
| Firmware: Body-Timeout | Header kam, Body nicht (50 ms) | Empfang abbrechen, wieder auf Sync warten | 50 ms |
| Watchdog: Client getrennt | Socket geschlossen (Absturz, Ctrl-C, SSH weg) | Alle Motoren `speed 0` | sofort |
| Watchdog: Idle-Timeout | Verbindung offen, aber 20 s kein Befehl | Alle Motoren stoppen | 20 s |
| Watchdog: rpm-Stall | Sollwert ≠ 0, rpm = 0 nach 3 s Gnadenfrist | Alle Motoren stoppen | 3–4 s |
| Watchdog: Überstrom | \|val1\| oder \|val2\| > 15 A | Alle Motoren stoppen | 1–3 s |
| Watchdog: Strom-Signatur | > 0,15 A bei rpm = 0 | Nur Log-Warnung, noch kein Stopp | 1 s |
| Mensch | Alles andere | Hand am Netzteil bzw. Akku-Trennung, besonders bei Sweeps | – |

**Motor-Freigabe:** Jeder Befehl, der einen Motor bewegen kann (Watchdog mit `--live`, Joystick mit `--live`, Mess-Skripte, Flashen mit Reset), braucht jedes Mal eine ausdrückliche Zustimmung im Moment. Ohne `--live` laufen Watchdog und Joystick als Trockenlauf und berühren den Bus nicht.

**Grenze der Stromüberwachung:** Der 15-A-Stopp ist ein Schutz gegen *anhaltenden* Überstrom. Kurze Spitzen (eine blockierte Wicklung kann Hunderte Ampere ziehen) sättigen den Sensor und sind so nicht abfangbar. Der Shunt auf der STM32-Platine selbst ist durchgebrannt und überbrückt, interne Strommessung gibt es dort nicht.

03

## LIN-Bus & Adressierung

addresses.json · generate_addresses.py · linbus.py

LIN läuft hier über einen Ein-Draht-Transceiver mit 19 200 Baud. Jedes gesendete Byte kommt als Echo zurück und muss gelesen und verglichen werden, sonst gerät der Master aus dem Takt. Die PID legt fest, ob der Master schreibt oder der Slave antwortet.

Bei einem Lese-Frame sendet der Master nur Sync und PID. Danach antwortet der Slave mit den Datenbytes und seiner Checksumme, die der Master nachrechnet (Abweichung: `ret −6`, keine Antwort in 2 s: `ret −5`).

### PID-Tabelle

Jeder Nachrichtentyp belegt einen Block aus 4 PIDs. Die untersten zwei Bits sind die Instanz. Die Firmware ist auf allen Motorplatinen identisch; welche Instanz eine Platine ist, entscheiden die Jumper an PB14/PB15 beim Booten (ohne Jumper: Instanz 3).

| Name | Basis-PID | Bytes | Richtung | Bedeutung | Watchdog-Verb |
| --- | --- | --- | --- | --- | --- |
| cntl0mot | 0x00 | 2 | Master → Motor | P- und I-Delta (je int8 × 0,01) | pi |
| cntl1mot | 0x04 | 2 | Master → Motor | Ein offener Kommutierungspuls (int16) | pulse, burst |
| cntl2mot | 0x08 | 6 | Master → Motor | Reset: Sollwert, Integral, Zähler, sysError | reset |
| cntl3mot | 0x0C | 2 | Master → Motor | Drehzahl-Sollwert (int16, big-endian) | speed |
| st0mot | 0x10 | 3 | Motor → Master | Hall-Bits H1, H2, H3 | hal |
| st1mot | 0x14 | 2 | Motor → Master | Temperatur (ADC roh) | temp |
| st2mot | 0x18 | 2 | Motor → Master | rpm (int16, Raster 25) | rpm |
| st3mot | 0x1C | 6 | Motor → Master | Timeout- und Checksummenzähler, Kickstart-Zähler, sysError | status, kickcount |
| cntl0cur | 0x20 | 2 | Master → Strom | LED-Test, Fehlerspeicher-Inject/Reset, Sabotage-Flag für Selbsttest | selftest |
| st0cur | 0x24 | 4 | Strom → Master | Zwei 10-Bit-ADC-Werte (val1, val2) | current |
| st1cur | 0x28 | 8 | Strom → Master | Letzte 8 Fehlercodes | errors |
| cntl0lig | 0x30 | 2 | Master → Licht | reserviert | – |
| st0lig | 0x34 | 4 | Licht → Master | reserviert | – |

### Eine Quelle, vier Ausgaben

**addresses.json**PIDs, Bytes, Richtung, Instanzen

→

**generate_addresses.py**läuft auf Windows

→

**raspi/control/linaddresses.py**Master-Sicht inkl. `pid_names`

**STM32/…/addresses.h**identisch für alle Slaves

**currentsensor/firmware/addresses.h**

**addresses.md**belegte und freie Blöcke

So benutzt du es Windows · Repo-Root

1. Nur `addresses.json` bearbeiten, die erzeugten Dateien nie von Hand.
2. Generator laufen lassen. `build.sh` bricht ab, wenn `addresses.json` neuer ist als `addresses.h`.
3. Danach Firmware bauen/flashen und den Pi neu deployen, damit beide Seiten dieselbe Tabelle haben.

```
python generate_addresses.py
```

### Fehlercodes von `linbus.py`

| ret | Name | Bedeutung |
| --- | --- | --- |
| 0 | – | Erfolg |
| −1 | ERR_UNKNOWN_PID | PID nicht in der Tabelle |
| −2 | ERR_WRONG_LENGTH | Datenlänge passt nicht zur Nachricht |
| −3 | ERR_WRONG_DIRECTION | Schreiben auf eine Lese-PID oder umgekehrt |
| −4 | ERR_ECHO_MISMATCH | Echo stimmt nicht (Kollision, Störung) |
| −5 | ERR_TIMEOUT | Slave antwortet nicht innerhalb von 2 s (nicht vorhanden, gehalten, stromlos) |
| −6 | ERR_BAD_CHECKSUM | Checksumme der Slave-Antwort falsch |

### Timing

Ein Byte braucht 0,52 ms auf dem Draht. Ein `speed`-Frame (5 Byte) also 2,6 ms, `status` (9 Byte) 4,7 ms. Gemessen werden pro Befehl 4,8 bis 8,9 ms, weil jedes Byte einen eigenen Schreib- und Lese-Aufruf kostet. Der Stresstest (Issue #24) hat gezeigt: Ein Paket aus `speed`, `rpm` und `status` für beide Motoren läuft bis 50 ms Takt sauber; bei 30 ms kommt der Zeitplan nicht mehr hinterher, ohne dass Bus oder Firmware Fehler zeigen.

04

## Watchdog

raspi/watchdog/watchdog.py · linbus.py

Der Watchdog ist ein eigener Prozess und der einzige, der `/dev/ttyS0` öffnet. Er entscheidet nicht, *was* der Motor tun soll, sondern prüft jeden Befehl gegen feste Grenzen, legt ihn auf den Bus und überwacht parallel den Motor auf eigene Faust.

Haupt-Thread · ein Client gleichzeitig

**listener.accept()**Client verbindet → Idle-Uhr startet

→

**conn.recv()**ein Textbefehl

→

**validate()**Syntax, Instanz, Wertebereich; sonst `ERR …`

→

**with lock: \_dispatch()**linbus-Aufruf, Stall-Buchführung

→

**conn.send()**`OK …` mit Messwerten

**EOFError**Client weg

→

**on_disconnect()**alle bekannten Motoren `speed 0`

monitor()-Thread · jede Sekunde · überlebt jeden Einzelfehler

**check_idle()**> 20 s still bei offener Verbindung → Stopp

→

**poll_rpm()**Motor 0 immer, andere nur wenn Sollwert ≠ 0

→

**\_check_stall()**rpm = 0 nach 3 s Gnadenfrist → Stopp

→

**poll_current()**> 15 A → Stopp · 0,15 A bei rpm 0 → nur Log

Beim Start · \_startup_reset()

**status 0, status 1**wer antwortet? alter Zustand wird geloggt

→

**reset**bedingungslos für jede antwortende Instanz

→

**Buchführung**beide Motoren sind ab Sekunde 0 „bekannt“

### Feste Grenzen

| Konstante | Wert | Warum |
| --- | --- | --- |
| SPEED_MIN/MAX | ±3000 | Sicherheitsgrenze unter dem physikalischen Maximum |
| PULSE_SPEED_MIN/MAX | ±1274 | Ab 1275 µs (GLOBALRATE) tut `driveState()` nichts mehr |
| PI_DELTA_MIN/MAX | −1,28…1,27 | Exakt der Bereich der int8×100-Kodierung |
| MOTOR / CURRENT_INSTANCE | 0–3 / 0–1 | Reservierte Kapazität im Adressschema |
| IDLE_TIMEOUT | 20 s | Menschen tippen mit Pausen |
| RPM_POLL_INTERVAL | 1 s | Takt des Überwachungs-Threads |
| STALL_GRACE_PERIOD | 3 s | Anlauf und Haftreibung nach 0 → ≠ 0 |
| OVERCURRENT_STOP_THRESHOLD | 15 A | Im linearen Bereich des ACS712 (Sättigung \~20 A), knapp unter dem Nennstrom von \~16–17 A |
| CURRENT_STALL_THRESHOLD | 0,15 A | Abstand zum Offset-Unterschied der Sensorchips |

### Befehlsreferenz

`<m>` = Motorinstanz 0–3, `<s>` = Stromsensor-Instanz 0–1. Die Instanz ist immer Pflicht, es gibt keinen Standardwert.

| Befehl | Wirkung | Antwort (Beispiel) |
| --- | --- | --- |
| speed \<m> \<v> | Drehzahl-Sollwert setzen, 0 = Stopp | OK |
| pi \<m> \<dp> \<di> | KP = 0,19 + dp, KI = 0,44 + di. Immer relativ zum Firmware-Standard, nie kumulativ | OK |
| pulse \<m> \<v> | Ein offener Kommutierungsschritt ohne PI-Regler | OK |
| burst \<m> v1 p1 v2 p2 | Puls v1, p1 ms warten, Puls v2, p2 ms warten (Losreißen aus der Mittelrast) | OK |
| reset \<m> | Firmware-Zustand löschen, Motor steht danach | OK |
| rpm \<m> | Drehzahl lesen | OK ret=0 rpm=500 (hex=0x01f4) |
| hal \<m> | Hall-Zustand lesen | OK ret=0 data=\['0x00','0x01','0x00'\] |
| temp \<m> | Temperatur-ADC lesen | OK ret=0 temp=… |
| status \<m> | Zähler und sysError | OK ret=0 timeout=0 checksum=0 kickstart=3 sys_error=-65 |
| kickcount \<m> | Nur der Kickstart-Zähler (mod 256) | OK ret=0 kickcount=3 |
| current \<s> | Strom beider Kanäle in A | OK ret=0 val1=2.34 val2=0.05 |
| errors \<s> | Fehler-Ringpuffer des Stromsensors | OK ret=0 codes=\[…\] names=\['CHK',…\] |
| selftest | 4-teiliger Selbsttest für Motor 0 + Sensor 0 (\~2 s): Fehlerspeicher, Sensor-Checksumme, Bus-Hang, Motor-Checksumme, Reset | OK inject_ret=0 … |

So benutzt du es Pi · /home/pi/auto

1. Watchdog in einem eigenen Terminal starten. Ohne `--live` ist es ein Trockenlauf mit `DryRunLin`: jedes Byte wird nur ausgegeben.
2. `--debug` zeigt den kompletten LIN-Trace auch im Terminal. In `watchdog.log` steht er immer, unabhängig vom Flag. Das Log wird bei jedem Start einmal rotiert (`watchdog.log.1`).
3. Dann genau einen Client verbinden: `motorcontrol.py` *oder* `joystick.py` *oder* ein Mess-Skript.

```
# sicher: kein Buszugriff
python3 watchdog.py

# echter Bus (Freigabe nötig), Trace im Terminal
python3 watchdog.py --live --debug
```

05

## Bedien-Clients

raspi/control/

Clients sprechen nie direkt mit dem Bus, sondern halten eine dauerhafte Verbindung zum Watchdog. Bricht sie ab, stoppt der Watchdog sofort. Deshalb nutzen alle Skripte eine einzige Verbindung für die ganze Sitzung und nicht pro Befehl eine neue.

### motorcontrol.py · Kommando-Konsole

Eine kleine interaktive Konsole mit Pfeiltasten-Historie. Jede Zeile wird unverändert an den Watchdog geschickt; Befehl und Antwort landen zusätzlich in `motorcontrol.log`. Für Skripte gibt es `send_command()`, das eine Verbindung pro Befehl öffnet (Achtung: das Schließen stoppt dann jeweils den Motor).

So benutzt du es Pi · zweites Terminal

```
python3 motorcontrol.py
motorcontrol> status 0
motorcontrol> speed 0 500
motorcontrol> rpm 0
motorcontrol> current 0
motorcontrol> speed 0 0
motorcontrol> exit
```

Nach einer längeren Fahrt besser in Stufen herunterfahren (z. B. 500 → 300 → 100 → 0): ein abruptes `speed 0` bremst härter als Auslaufen.

### joystick.py · Fahren mit dem Logitech F710

Liest den rechten Stick über `pygame`, rechnet daraus Differentialantrieb und schickt alle 200 ms für beide Motoren einen `speed`-Befehl. Das dient gleichzeitig als Herzschlag gegen den 20-s-Idle-Timeout. Läuft nie parallel zu `motorcontrol.py`.

Mischung

vor = −achse\[4\] (Stick weg vom Körper = +) lenk = achse\[3\] links = clamp(vor + lenk) · 1200 · Richtung_L rechts= clamp(vor − lenk) · 1200 · Richtung_R |wert| \< 500 → 0 (Deadzone in Drahteinheiten)

Totmann-Prinzip

Jede Änderung der Fahrgeschwindigkeit oder ein Zucken am linken Trigger (LT, Achse 2, > 0,05) bestätigt für 10 s. Läuft das Fenster ab, fahren beide Motoren in 5 Stufen über 1 s auf 0. Ein eingefrorenes Funksignal hält alle Achsen konstant und läuft deshalb sicher ab.

Rote Taste B · Recovery

Wirkt nur, wenn ein Motor wirklich `sys_error = −65` meldet. Dann: `reset` des blockierten Motors, 2–3 sanfte Schritte (±500 speed, ±1000 pulse), Prüffahrt beider Motoren mit 800 für 1,5 s, Rampe auf 0, Eintrag in `recovery_sequences.csv`.

Vibration als Rückmeldung

Alle 0,2 s `rpm` und `status` beider Motoren. Steigt der Kickstart-Zähler in einer Blockade um ≥ 2: kurze Vibration (1 s). Bestätigte Blockade: lange Vibration (2 s), einmal pro Episode. Läuft über `evdev`; fehlt es, wird ohne Vibration gefahren.

So benutzt du es Pi · Watchdog läuft mit --live

1. Erst ohne `--live` starten: es wird nichts gesendet, nur angezeigt, was gesendet *würde*. Mit `--debug` siehst du jede Achse und Taste, gut zum Kalibrieren.
2. `--left/--right` = welche Motorinstanz links/rechts sitzt, `--left-dir/--right-dir` = ob das Vorzeichen gedreht werden muss (`cw` nein, `ccw` ja). Alle vier sind Pflicht.
3. Für echte Fahrt `--live` anhängen. Fährt los, sobald du den Stick bewegst.

```
# Probelauf ohne Motorbewegung
python3 joystick.py --left 0 --right 1 --left-dir cw --right-dir ccw --debug

# echte Fahrt (Freigabe nötig)
python3 joystick.py --left 0 --right 1 --left-dir cw --right-dir ccw --live
```

Weitere Optionen: `--max-rpm` (1200), `--deadzone` (500), `--confirm-timeout` (10), `--poll-interval` (0,2), `--stall-poll-interval` (0,2), `--axis-forward/--axis-steer/--axis-lt`, `--recovery-button`, `--joystick-index`.

06

## Mess- & Testskripte

raspi/control/ · raspi/analyze_logs.py

Alle Mess-Skripte laufen auf dem Pi gegen einen laufenden `--live`-Watchdog, schreiben ihre Messdaten als CSV auf stdout und das Protokoll in eine eigene `.log`-Datei. Die CSV musst du selbst umleiten, sonst ist sie weg.

### capture_step_response.py · Sprungantwort

Das Arbeitspferd der P/I-Suche: ein Sprung von 0 auf 1000 rpm, 7 s lang alle 200 ms `rpm`, jede Sekunde `current`. Erkennt Blockaden selbst und versucht einmal, den Motor zu befreien.

Der Soft-Stop läuft nur, wenn mindestens die halbe Zieldrehzahl erreicht wurde und kein Stall gemeldet ist; sonst würden die absteigenden Sollwerte die Blockadeerkennung neu auslösen. Eine zweite Blockade im Wiederholungsversuch bricht ab.

Recovery-Katalog

`speed0`, `speed_plus/minus` (±500), `speed_max_plus/minus` (±1000), `pulse_plus/minus` (±1000), `burst_cw/ccw`. Zufällig 2–3 Schritte, höchstens 1 burst, 2 pulse, 1 Vollgas, keine direkte Wiederholung, ≥ 100 ms Pause.

Zwei Motoren

Mit `--motor1` laufen beide mit demselben Ziel. Blockiert einer: erst reset, dann den gesunden per Rampe stoppen, Recovery nur am blockierten, beide wiederholen. Blockieren beide: Abbruch ohne Recovery. Hardware-Test offen

Trainingsdaten

Jeder Recovery-Versuch schreibt zwei Zeilen in `recovery_sequences.csv` (Phase `sequence` und `retry`, verbunden über den Zeitstempel). Die Datei wird nie rotiert. Bei Schemaänderung von Hand leeren.

So benutzt du es Pi · Watchdog --live

```
# Standard: Motor 0, Firmware-Gains, Ziel 1000
python3 capture_step_response.py > sprung.csv

# mit P/I-Delta und zweitem Motor
python3 capture_step_response.py --p-delta 0.02 --i-delta 0.0 --motor0 0 --motor1 1 > sprung_dual.csv
```

Weitere Optionen: `--target-speed` (±), `--current-instance`. Ein abgelehntes `pi` bricht ab, bevor der Motor angefasst wird. Danach mit dem Skill `/plot-step-response` als Diagramm darstellen.

### Weitere Skripte

| Skript | Was es tut | Aufruf |
| --- | --- | --- |
| validate_speed.py | Rampe 0 → 400 → 800 → 1200 → … → −1200 → 0, nach jedem Schritt 3 s warten und `rpm` + `current` lesen. Prüft, ob `speed` wirklich rpm bedeutet. | python3 validate_speed.py --motor 0 > ramp.csv |
| validate_motor_currentsensor.py | Regressionstest Motor + Stromsensor am selben Bus: 0 → 500 → 1000 → 500 → 0, jeweils `current`, `hal`, `rpm` | python3 validate_motor_currentsensor.py |
| validate_lin_stress.py | Buslast-Test mit `speed 0` (bewegt nichts): pro Takt `speed/rpm/status` für beide Motoren, langsamer `hal/current/errors`. Meldet Zeitplan-Verzug und Zählerdifferenzen. | python3 validate_lin_stress.py --tick-rate 0.1 \| tee stress.csv |
| characterize_hall_positions.py | Findet je Hall-Position die Losbrech-Pulsstärke (750 → 1100 in 25er-Schritten). Einmal von Hand positionieren, dann fährt es ein Rotorviertel selbst ab. | python3 characterize_hall_positions.py |
| analyze_logs.py | Liest Logs offline (Windows): hängende Aufrufe ohne Antwort, `ret ≠ 0`, Latenz > 50 ms, falsche Datenlängen, WARNING/ERROR, Lücken > 1,5 s im Poll-Takt. Exit-Code 1 bei Befund. | python raspi/analyze_logs.py runs/x/watchdog.log |
| lincomm.py | Alter, ursprünglicher LIN-Code (direkter Buszugriff, importiert pygame/numpy). Nur Referenz, wird nicht deployt. | nicht benutzen |

07

## STM32-Firmware

STM32/firmware/Core/Src/main.c

Ein STM32H743 pro Motor. Die Hauptschleife wechselt zwischen zwei Aufgaben: solange keine LIN-Nachricht vollständig ist, regelt und kommutiert sie den Motor; kommt eine Nachricht an, wird sie ausgewertet und die Schleife beginnt von vorn. Den Empfang erledigt eine Interrupt-Routine im Hintergrund.

Die Regelschleife ist während des Wartens auf LIN-Bytes immer aktiv. Der kritische Moment ist der Dispatch: dort ist der Header-Empfang kurz nicht scharf. Deshalb macht jeder Handler nur sehr wenig (höchstens einen 1275-µs-Schritt); längere Puls-Folgen laufen als `burst` auf der Pi-Seite.

### Kommutierung

Klassische 6-Schritt-Blockkommutierung. `driveStep()` liest die drei Hall-Eingänge PC0–PC2 und bestromt die Phase für den *nächsten* Zustand. Vorwärts (positiver Sollwert) laufen die Zustände aufsteigend, rückwärts absteigend.

| Hall H1 H2 H3 | Zustand | CW: bestromt | Phasen | CCW: bestromt |
| --- | --- | --- | --- | --- |
| 0 0 1 | 0 | 1 | A low, C high | 2 |
| 0 1 1 | 1 | 2 | B low, C high | 3 |
| 0 1 0 | 2 | 3 | B low, A high | 4 |
| 1 1 0 | 3 | 4 | C low, A high | 5 |
| 1 0 0 | 4 | 5 | C low, B high | 0 |
| 1 0 1 | 5 | 0 | A low, B high | 1 |

Die Spalte „Phasen“ gehört zum bestromten Zustand der CW-Spalte. Bekannte Problemstelle: die „Mittelrast“ zwischen Zustand 2 (010) und 3 (110), in der der Motor reproduzierbar hängen bleibt.

Die Stellgröße des PI-Reglers ist direkt die Einschaltzeit in µs. Begrenzt auf ±1175 (CONTROLLIMIT = GLOBALRATE − 100). Etwa 785 Schritte pro Sekunde.

### PI-Regler

e = soll − rpm u = KP · e + KI · DT · ∫e KP = 0,19 + dp KI = 0,44 + di DT = 1,275 ms |u| > 1175 → u begrenzen, Integral nur weiterführen, wenn der Fehler es verkleinert (Anti-Windup) soll = 0 → Integral = 0, u = 0

Die Standardwerte 0,19/0,44 sind das Ergebnis der abgeschlossenen P/I-Suche vom 10.09.2026 (vorher 0,15/0,40, etwa 27 % besseres ISE). `rpm` ist auf Vielfache von 25 gerastert, weil in 100-ms-Fenstern ganze Hall-Flanken gezählt werden.

### Kickstart und Blockade-Erkennung

Jedes 100-ms-Fenster mit Sollwert ≠ 0 und rpm = 0 zählt `stuckwindowcount` hoch. Dreht sich der Motor wieder, geht der Zähler auf 0.

Der Kick-Puls ist bewusst schwach. Mit 800 (\~63 % Tastgrad) brannten am 08.09.2026 zwei MOSFETs einer Halbbrücke durch. Das eigentliche Befreien aus der Mittelrast übernimmt die Pi-Seite mit `burst` oder einem Neustart mit höherem Sollwert.

### Status-Antwort st3mot

| Byte | Inhalt |
| --- | --- |
| 0–1 | `bodyTimeoutCount`: Nachrichten, deren Body nie kam |
| 2 | `checksumErrorCount`: abgelehnte, eigene Master-Writes |
| 3 | `kickStartCount` (mod 256, nur durch `reset` genullt) |
| 4 | `sysError`: 0 = OK, −8 = LIN-Empfangsfehler, −65 = Blockade |
| 5 | frei (0) |

So benutzt du es Windows · Git Bash

1. **Bauen**: immer `make clean` + Neubau mit dem in STM32CubeIDE eingebauten arm-gcc. Ausgabe `STM32/firmware/Debug/demoboard.elf`, Meldungen auch in `STM32/build.log`.
2. **Flashen** (Freigabe nötig): schreibt und verifiziert über ST-Link/SWD. Ohne `--reset` bleibt der Controller danach angehalten, bis du SW2 drückst. `--reset` startet sofort und ist eine eigene Freigabe.
3. Meldet der Programmer „Unable to get core ID“: Platine einmal stromlos machen und erneut flashen. Die Spannungsanzeige 0,01 V ist immer so und sagt nichts.

```
bash STM32/build.sh
bash STM32/flash.sh
bash STM32/flash.sh --reset
```

Alternativ die Skills `/build-stm32` und `/flash-stm32`.

08

## Sensor-Slaves

currentsensor/ · lightsensor/

Stromsensor · ATmega328P

#### Zwei Kanäle, ein Board

Zwei ACS712-20A-Hallsensoren an ADC 2 und 3. Ein Timer-1-Interrupt misst abwechselnd beide Kanäle und mittelt über ein \~1-s-Fenster. Über LIN gehen die rohen 10-Bit-Werte; der Pi rechnet in Ampere um, weil der AVR keine Gleitkomma-Einheit hat.

I = (roh · 5 V / 1024 − 2,5 V) / 0,1 V/A roh 512 → 0 A

Eigener Fehler-Ringpuffer (8 Codes: SYN, PAR, PID, MSI, CHK, TIM, IND, NUM), lesbar mit `errors 0`. Checksummen-Gate für `cntl0cur`. Liest seine Instanz-Jumper noch nicht (Issue #1), ist fest Instanz 0.

Lichtsensor · ATmega328P

#### Startpunkt aus dem Kursprojekt

Firmware-Fragmente aus dem DCPS-Kursprojekt. Baut (`light.hex`), hat aber noch keine LIN-Adresstabelle und keine Checksummen-Prüfung. PIDs sind reserviert. Echte Umsetzung: Issue #11.

geplant

So benutzt du es Windows

Beide AVR-Projekte bauen mit ihrem eigenen `Makefile` (avr-gcc). Geflasht wird von Hand, dafür gibt es im Repo kein Werkzeug. Lesen über den Watchdog: `current 0`, `errors 0`, `selftest`.

```
make -C currentsensor/firmware
```

09

## Optimierung & Analyse

run_experiment.py · run_grid.py · run_grid_row.py · analysis/ · saleae_mcp/

Diese Skripte laufen auf Windows und fernsteuern den Pi über SSH. Sie rufen dort `capture_step_response.py` mit verschiedenen P/I-Deltas auf, holen die CSVs zurück und bewerten sie. Die P/I-Suche ist seit 10.09.2026 abgeschlossen; die Werkzeuge bleiben für spätere Messungen unter Last.

### Die drei Runner

#### run_grid.py · 3×3-Gitter

P−

P 0

P+

I+

−p,+i

0,+i

+p,+i

I 0

−p,0

0,0\
Standard

+p,0

I−

−p,−i

0,−i

+p,−i

#### run_grid_row.py · 9 Punkte auf einer Achse

−4s−3s−2s−1s0+1s+2s+3s+4s

Eine Achse variiert, die andere bleibt fest. Harte Sperre: kein Punkt mit P-Delta > 0,10, weil dort hörbares Ruppeln begann.

#### run_experiment.py · ein Punkt mit Saleae

Checkliste, Saleae im Trigger-Modus scharf, Motorlauf, bis zu 3 Wiederholungen bei Fehltrigger durch EMV, Log-Prüfung, Plot Hall-rpm gegen LIN-rpm.

### Bewertung

ISE · Regelgüte

ISE = Σ (1000 − rpm)²

Große Abweichungen zählen überproportional. Bestimmt den „besten Punkt“ und dessen Diagramm.

MSSD · Rauheit

MSSD = mittel (rpm\[i+1\] − rpm\[i\])²

Fängt Pendeln, das ISE nicht sieht. Zwei Fenster: die ersten 2 s und die vollen 7 s.

Auswahlregel

P so hoch wie die Rauheit zulässt (mehr P bringt Dämpfung unter Last). I nur so hoch wie nötig gegen bleibende Abweichung, mit Reserve für die späteren \~50 kg Fahrzeuglast.

So benutzt du es Windows · Repo-Root · Watchdog auf dem Pi --live

1. Hand am Netzteil bzw. an der Akku-Trennung bleiben: eine Zustimmung deckt das ganze Gitter oder die ganze Reihe ab.
2. Ohne Argumente fragen die Skripte interaktiv nach den Werten.
3. Ergebnisse landen in `runs/<zeitstempel>_grid/` bzw. `_row/`: pro Punkt CSV + Log, `grid_results.csv`, Diagramm des besten Punkts, `watchdog.log`.
4. Abbruch mit Ctrl-C: Das Skript schickt zusätzlich `speed 0` und notiert, nach welchem Punkt abgebrochen wurde.

```
# ein Punkt mit Saleae (Logic 2 mit Automation auf Port 10430)
python run_experiment.py 0.02 0.0

# 3×3 um den Standard: |p_delta| |i_delta|
python run_grid.py 0.04 0.04

# Reihe: Achse, fester Wert der anderen Achse, Schrittweite
python run_grid_row.py p 0.0 0.02

# mehrere Läufe zu Heatmaps zusammenführen
python analysis/grid_heatmap.py runs/2026-08-25_xxxx_grid runs/2026-08-25_yyyy_row
```

### Saleae und Hall-Auswertung

`analysis/hall_rpm.py` entprellt die rohen Hall-Flanken (Spitzen kürzer als 1 µs sind EMV beim Schalten der MOSFETs), zählt 24 Flanken pro Umdrehung und bildet 100-ms-Fenster, direkt vergleichbar mit der Firmware. `has_sustained_high()` unterscheidet einen echten Trigger (Sekunden HIGH) von einer Störspitze. Die zeitliche Ausrichtung beider Quellen läuft über die steigende Flanke des Trigger-Pins, die mit dem `speed`-Befehl zusammenfällt.

`saleae_mcp/server.py` stellt Claude Code die Saleae als Werkzeuge bereit: `list_devices`, `start_capture` (manual, timed, trigger), `wait_for_capture_or_timeout`, `stop_capture`, `export_capture`, `save_capture`, `close_capture`. Voraussetzung: Logic 2 läuft mit aktiviertem Automation-Server.

**Aktuell:** Der MCP-Server `saleae` konnte in dieser Sitzung nicht verbinden. In `.mcp.json` zeigen Python- und Server-Pfad auf `C:\Users\rembo\…`; auf diesem Rechner liegt das Repo unter einem anderen Benutzer. Pfade anpassen, dann Claude Code neu starten.

10

## Werkzeuge & Prozess

raspi/deploy.sh · raspi/tests/ · .claude/skills/ · issues/

Deploy

`raspi/deploy.sh` kopiert alle Pi-Skripte flach nach `/home/pi/auto/`, mit 3 Versuchen pro Aufruf gegen wackeliges mDNS. Führt nichts aus. Die zweite CLAUDE.md heißt dort `watchdog-CLAUDE.md`.

Tests

Jede Änderung unter `raspi/control` oder `raspi/watchdog` braucht vorher einen grünen `pytest raspi/tests/`. Getestet wird Logik mit DryRunLin und Mocks, nicht echtes Motorverhalten.

Skills

`/build-stm32`, `/flash-stm32`, `/deploy-raspi`, `/run-raspi-validation`, `/saleae-trigger-capture`, `/plot-step-response`, `/plot-saleae-step-response`, `/analyze-logs`.

Review mit Codex

GitHub-Issues sind der Status. Pro Issue eine Datei `issues/I-000N.md`: Claude schreibt, Codex prüft nur und setzt `review: done`, der Autor entscheidet. Details in `PROCESS.md` und `AGENTS.md`.

So benutzt du es Windows · Repo-Root

```
pytest raspi/tests/
bash raspi/deploy.sh
ssh pi@motorpi.local
```

11

## Typische Abläufe

Rezept A

#### Motor von Hand testen

1. Akku/Netzteil an, Instanz-Jumper prüfen.
2. Pi: `python3 watchdog.py --live`
3. Zweites Terminal: `python3 motorcontrol.py`
4. `status 0` → `speed 0 500` → `rpm 0` → stufenweise auf `0`
5. Windows: `/analyze-logs`

Rezept B

#### Fahrzeug fahren

1. Watchdog `--live` starten.
2. Joystick einmal ohne `--live` mit `--debug` prüfen.
3. Mit `--live` fahren. Für Konstantfahrt ab und zu LT antippen.
4. Blockade: Vibration → rote Taste B.

Rezept C

#### Firmware ändern

1. `main.c` bearbeiten; bei Adressen erst `addresses.json` + Generator.
2. `bash STM32/build.sh`
3. Freigabe → `bash STM32/flash.sh`, dann SW2 drücken.
4. `selftest` und kurzer `speed`-Test.

Rezept D

#### Pi-Code ändern

1. Im Repo ändern, nie direkt auf dem Pi.
2. `pytest raspi/tests/` muss grün sein.
3. `bash raspi/deploy.sh`
4. Watchdog neu starten (der alte läuft sonst mit dem alten Code).

Rezept E

#### Sprungantwort messen

1. Watchdog `--live`.
2. `python3 capture_step_response.py > runs/x.csv`
3. CSV holen, `/plot-step-response`.
4. Mit Saleae: `/saleae-trigger-capture` bzw. `run_experiment.py`.

Rezept F

#### Bus prüfen

1. `selftest` in motorcontrol (≈ 2 s, bewegt nichts).
2. `validate_lin_stress.py --tick-rate 0.1`
3. Zusammenfassung auf stderr: Verzug und Zählerdifferenzen müssen 0 sein.

12

## Offene Punkte & Auffälligkeiten

Was beim Lesen des Codes aufgefallen ist oder laut Doku noch aussteht.

| Bereich | Punkt | Art |
| --- | --- | --- |
| joystick.py | Zweiter Fix der Langvibration (Erkennung vs. Bestätigung getrennt) ist noch nicht mit einer echten Blockade bestätigt (Issue #22). Recovery-Taste B noch nie gegen echte Blockade getestet (Issue #21). | HW-Test |
| capture_step_response.py | Zwei-Motor-Modus (`--motor1`) nur mit pytest getestet (Issue #4). | HW-Test |
| watchdog.py | Strom-Stall-Signatur nur beobachtend und nur für val1/Motor 0 (Issue #18). `selftest` fest auf Motor 0/Sensor 0. | offen |
| watchdog.py | Was stoppt den Motor, wenn der Watchdog-Prozess selbst ausfällt? (Issue #15). Einzelne Schutzpfade nie gezielt einzeln getestet (Issue #16). | offen |
| Mess-Skripte | Fehlgeschlagene Lesungen landen als „None“ in der CSV statt Alarm zu geben (Issue #13). | offen |
| Firmware | Keine Plausibilitätsgrenze für KP/KI und keine Rückmeldung der aktiven Werte (Issue #6). Funktionen `driveStepKickStart*` sind toter Code. | offen |
| watchdog.py | Kommentar zu `OVERCURRENT_STOP_THRESHOLD` sagt, 15 A liege „klar über“ dem Nennstrom von \~16–17 A. Rechnerisch liegt es darunter; bei Volllast könnte der Stopp auslösen. Schwelle oder Kommentar prüfen. | prüfen |
| STM32/flash.sh | Kommentar nennt als Standard `BringUpBoard.elf`, der Code nutzt korrekt `demoboard.elf`. | Kleinigkeit |
| Pfade | `.mcp.json`, `build.sh` (make.exe) und die Doku verweisen auf `C:\Users\rembo\…`. Auf diesem Rechner prüfen. | prüfen |
| Fahrzeug | Mehrprozess-Architektur, Lern-Algorithmus, SQLite-Log, Web-UI, IFM-Sensorik, GPS/ROS. | geplant |

Erstellt aus dem Quellcode und den CLAUDE.md-Dateien des Repos `auto` (Commit c60dcb3), Stand 7. Oktober 2026.