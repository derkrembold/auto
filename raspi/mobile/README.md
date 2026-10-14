# MotorPi: Android-App und Raspberry-Pi-Dienst

Flutter für Android, Bluetooth Low Energy zur Steuerung, zusätzlich ein
WLAN-Access-Point für SSH und APK-Download. Ohne Internet nutzbar.

## Installation und Bedienung

1. Mit WLAN **MotorPi** verbinden und die Verbindung ohne Internet beibehalten.
   Das WLAN-Passwort steht in den privat bereitgestellten Zugangsdaten.
2. `http://10.42.0.1:8080/` öffnen, APK herunterladen und installieren.
   Im bisherigen LAN geht auch `http://motorpi.local:8080/`.
3. Bluetooth einschalten. In der App den separaten achtstelligen Zugangscode
   eingeben, **MotorPi suchen**, Gerätezugriff erlauben und MotorPi auswählen.
   Unter Android 7–11 ist für den BLE-Scan die Standortberechtigung erforderlich;
   gegebenenfalls auch den Standortschalter einschalten. Den Pi nicht vorher
   über die Android-Systemeinstellungen koppeln.
4. Bei neutralen Eingaben **Start** drücken. Den festen Joystick bewegen.
   Seine Stellung bleibt beim Loslassen erhalten. **Stopp** hält beide Motoren an.
   Danach erneut starten. Der Fahrbildschirm scrollt nicht, auch im Querformat.
   Die Zahlen zeigen Sollwerte, keine gemessenen Drehzahlen.
5. Gamecontroller mit dem **Handy** koppeln oder per USB anschließen. In der App
   **Controller** auswählen: **A** = Start,
   **linker Stick** = Fahren/Lenken, **B** = Stopp. Der Gerätename erscheint nach
   der ersten Eingabe. Die letzte nichtneutrale Stickstellung bleibt aktiv,
   auch wenn der Stick in die Mitte zurückspringt. **B** beendet die Fahrt.

Das Limit ist anfangs 60 % von maximal 1200 U/min und gilt auch beim Lenken.
Wie im bestehenden Joystickcode werden Sollwerte unter 500 U/min zu null.
Kleine Stickbewegungen bleiben deshalb im Anlaufbereich. Es gibt keinen Stopp
allein wegen unveränderter Eingabe oder normalem Touch-Loslassen.
App-Wechsel, abgebrochene Touch-Geste, Controllertrennung und BLE-Ausfall
beenden die Fahrt. Ein Wechsel Touch/Controller stoppt zuerst.

## Stand der Auslieferung vom 14.10.2026

App-Version 0.2.0 ist bereitgestellt. Nach ausdrücklicher Freigabe läuft die
aktuelle Sitzung in **Echtbetrieb** mit Startfreigabe aus der App.
Ein freigegebener Einzeltest bestätigte Motor 0 als links, positiv = vorwärts,
mit gemessenen 600 U/min und anschließendem Rampenstopp. Die Pi-Startbefehle
für `joystick.py` enthalten `--left 0 --right 1 --left-dir cw --right-dir ccw`.
Der Benutzer hat einen weiteren Motor-1-Test auf Warten gesetzt und danach
ausdrücklich die Übernahme dieser bisherigen Zuordnung sowie den Live-Start
bestätigt. Ein erneuter Motor-1-Drehrichtungstest wurde nicht durchgeführt.
Die Live-Sitzung ist aktiv, beide Motor-/Stromstatusabfragen sind fehlerfrei,
die Sollwerte stehen zunächst auf null. Fahren mit der neuen App und dem
tatsächlichen Handy/Gamecontroller ist noch nicht geprüft. Beim Booten sowie
nach dem Ende der Sitzung startet wieder der Simulator.

Die APK ist ein Release-Build für Android ab API 24, derzeit mit dem lokalen
Android-Debug-Schlüssel signiert, für die Installation im Projekt. Für eine
dauerhafte Verteilung einen eigenen Release-Schlüssel außerhalb des Repo
verwenden. Keine Play-Store-Veröffentlichung.

Update 0.1.1 behebt den zu kurzen Drei-Sekunden-Abbruch beim Android-
Verbindungsaufbau: getrennte Dienstsuche (bis 15 s), danach Challenge lesen,
Statuskanal vollständig öffnen und Anmeldung über eine Statusmeldung bestätigen.
Fehlermeldungen nennen den betroffenen Schritt. Die kurzen Zeitlimits während
der Fahrt bleiben unverändert. Das Update über die vorhandene App installieren;
der persönliche Zugangscode bleibt gleich.

## Aufbau

```text
Touch / Android-Gamecontroller -> Flutter + Android-Eingabeadapter
  -> BLE (signierte Befehle und bestätigte Sequenznummern)
  -> ble_server.py -> control_core.py
  -> bridge.py (nur bei --live) -> vorhandener Watchdog -> LIN -> STM32
```

- `control_core.py`: Hardware-unabhängige Zustandsmaschine, HMAC-Anmeldung,
  Wiedergabeschutz, Mischung, Limits, Heartbeat, gemeinsame Stopprampe.
- `bridge.py`: ein persistenter IPC-Client des vorhandenen Watchdogs, kein
  eigener LIN-Master. Prüft vor jeder Geschwindigkeitsrunde beide Motorstatus
  und `current 0`; nicht endliche Ströme oder mehr als 15 A sperren die Fahrt,
  passend zum bestehenden Watchdog-Limit. Bei einem Fehler schließt der Client:
  Der vorhandene Watchdog stoppt dann alle bekannten Motoren.
- `ble_server.py`: BlueZ/D-Bus-Peripheral mit separatem Steuerungsthread.
- `install.py`, `deploy.ps1`: Installation ohne Motorstart.
- `tests/`: Logiktests, Linux-IPC mit eigenem Fake-Socket, BLE-Test, der
  einen als Echtbetrieb markierten Dienst ausdrücklich ablehnt.

Normaler Stopp/Loslassen/Verbindungsabbruch: proportionale Rampe beider Motoren
über 1 s. Heartbeat: fehlende gültige Befehle werden nach 0,6 s erkannt.
Wiederholtes Stopp verlängert die Rampe nicht. Die App wartet maximal 500 ms auf
eine Befehlsbestätigung und hält keine Fahrbefehle in einer Warteschlange.
Statusmeldungen kommen zusätzlich alle 200 ms.

Bei Hardware-/IPC-Fehlern wird die Störung gesperrt und der Watchdog-Client
geschlossen. Keine weiteren Rampenbefehle an einen bereits gestörten Motor.
Der Watchdog bestimmt dann den tatsächlichen Hardware-Stopp. Die App ersetzt
keinen physischen Not-Aus; Reaktionszeiten unter realer Last sind noch nicht
am Fahrzeug vermessen.

## BLE-Protokoll Version 1

UUID-Grundform `bc79000X-6a35-4c63-9419-00d9e185a101`:

| X | Rolle | Zugriff |
|---|---|---|
| 1 | Service | Werbung als MotorPi |
| 2 | Zufällige Challenge, 16 Bytes | Read |
| 3 | Anmeldung / Befehl | Write Without Response |
| 4 | Status, 20 Bytes | Read + Notify |

Anmeldung innerhalb 30 s: `0x00 || HMAC-SHA256(key, "auth" || nonce)[:16]`.
Pro Gerät eigene Challenge, genau ein Besitzer der Steuerung. Schlüssel:
16 Bytes. Neue Zugangscodes bestehen aus acht zufälligen Zeichen des Alphabets
`ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (40 Bit Entropie). Groß-/Kleinschreibung,
Leerzeichen und Bindestriche sind unerheblich. Ableitung:
`SHA256("MotorPi access code v1:" + normalisierter_code)[:16]`.
Die App akzeptiert außerdem alte 32-stellige Hex-Codes für nicht umgestellte Pis.
Nach fünf falschen Anmeldungen sind weitere Versuche bis zum Ende des laufenden
30-Sekunden-Fensters blockiert, auch bei wechselnden Bluetooth-Geräteadressen.

Befehl: Body `<BIhhB` (little endian) plus
`HMAC-SHA256(key, nonce || body)[:10]`, insgesamt 20 Bytes. Body: Opcode,
steigende uint32-Sequenz, Vorwärts/Lenkung jeweils -1000..1000, Flags.
Opcodes 1 Start, 2 Fahren, 3 Stopp. Bei Fahren: Bit 7 aktive Fahrfreigabe,
Bits 0..6 Limit 0..100 %. Start verlangt neutrale Werte und Flags.

Status `<BBBBhhIHH4x`: Version, Zustand, Flags, Fehler, links/rechts Sollwert,
letzte akzeptierte Sequenz, Maximal-RPM, Heartbeat-ms, vier reservierte Bytes.
Zustände 0 gestoppt, 1 freigegeben, 2 Rampe, 3 Störung. Flags: Bit 0 live,
Bit 1 angemeldet, Bit 2 bereit. Fehler 1 Verbindung/Eingabe ausgeblieben,
3 Hardware/IPC. Eine Störung lässt sich nicht aus der App zurücksetzen.

Auf diesem Pi mit BlueZ 5.50 liefen ATT Write Requests trotz erfolgreicher
D-Bus-Antwort in einen Timeout. Daher Write Without Response mit **eigener
Bestätigung über die Status-Sequenz**. Eine lokal abgeschlossene Schreiboperation
allein ist kein bestätigter Fahrbefehl. HMAC authentifiziert die Befehle;
dadurch wird der BLE-Datenaustausch nicht verschlüsselt. Status ist lesbar.

## Build und Deployment

Getestete Umgebung: Flutter 3.47.6 / Dart 3.13.5, JDK 23, Android compile SDK 36.
BLE-Pakete 5.4.0; ihr Compile-SDK wird auf 36 angehoben. Sie benötigen aktuell
den alten Kotlin/Android-DSL-Kompatibilitätsmodus. Die Gradle-Warnung zur
künftigen Umstellung auf Built-in Kotlin ist bekannt.

Wegen des langen Windows-Pfads wurde das Repo als `M:` eingebunden:
`subst M: <absoluter Repositorypfad>`. Flutter liegt ignoriert in `.tools/`.
Für Build-Aufrufe durchgehend den kurzen Pfad verwenden.

```powershell
cd M:\mobile_app
M:\.tools\flutter\bin\flutter.bat pub get
M:\.tools\flutter\bin\flutter.bat analyze
M:\.tools\flutter\bin\flutter.bat test
M:\.tools\flutter\bin\flutter.bat build apk --release
cd M:\
.\raspi\mobile\deploy.ps1 -Install -ApkPath .\mobile_app\build\app\outputs\flutter-apk\app-release.apk
```

Bei der ersten WLAN-Einrichtung zusätzlich `-AccessPoint` angeben. Sie verlangt
den bestehenden Ethernet-Uplink. Voraussetzungen: `python3-dbus`, `python3-gi`,
`bluez`, `hostapd`, `dnsmasq`. Auf dem vorhandenen Raspbian Buster wurden die
fehlenden WLAN-Pakete über eine temporäre Quellenliste der offiziellen
Raspberry-Pi-Archive installiert; keine dauerhafte APT-Quellenänderung und kein
OS-Upgrade. Python 3.7.3 und BlueZ 5.50 des Pi werden weiterverwendet.

Deployment: `/home/pi/auto/mobile/`, getrennt von bisherigen Watchdogdateien.
Konfiguration: `/etc/motorpi-mobile/config.json`. Zugangsdaten:
`/home/pi/auto/mobile/access.txt` (0600). Passwörter/Schlüssel niemals ins Repo
oder in den Downloadordner kopieren. Die App hält den Code nur im Speicher.

```sh
systemctl status motorpi-mobile motorpi-ap motorpi-dhcp motorpi-download
journalctl -u motorpi-mobile -n 40 --no-pager
```

Downloadserver: ausschließlich `/home/pi/auto/mobile/download/`, Port 8080.
WLAN `10.42.0.1/24`, DHCP `.10`–`.100`, WPA2, SSID MotorPi. Keine
Internetweiterleitung. Neue Dienste starten beim Booten; der BLE-Dienst bleibt
ohne `--live` immer in Simulation.

## Echtbetrieb: bestätigte Zuordnung und Sitzungsfreigabe

`raspi/CLAUDE.md`, **Motor Execution Consent**, verlangt vor jedem Live-Start
die ausdrückliche, unmittelbare Zustimmung. Deployment ist keine Motorfreigabe.
Vor Ort Fahrzeug sichern, Räder frei, Instanzen und Drehrichtungen in einzeln
abgesprochenen kurzen Tests bestimmen. Danach die lokale Pi-Konfiguration
eintragen: `left`, `right`, `left_dir`, `right_dir` (`cw` = positives Vorzeichen,
`ccw` = invertiert), `mapping_verified: true`, `live: true`. Nichts raten.
Am 14.10.2026 bestätigt: links 0/cw, rechts 1/ccw.

Erst nach Zuordnung und Zustimmung den Simulationsdienst stoppen, den vorhandenen
Watchdog in einer freigegebenen Live-Sitzung starten und den BLE-Dienst interaktiv
mit `--live` ausführen. Er startet mit null und verlangt zusätzlich Start plus
aktive Fahrfreigabe aus der App. Nicht parallel mit `joystick.py` oder
`motorcontrol.py` verbinden. Die installierte Systemd-Unit bleibt ohne `--live`.

`live_session.py` ist ein vorbereiteter Sitzungsstarter, standardmäßig ohne
Ausführung. Nur mit unmittelbarer menschlicher Zustimmung werden `--live`
und `--consent STARTFAHRT` verwendet. Er prüft die verifizierte Konfiguration,
stoppt den Simulator, startet Watchdog und BLE-Dienst als zusammengehörige
Sitzung und stellt beim Ende Simulation wieder her. Keine Live-Autostarts oder
automatischen Neustarts nach Störungen. `commission.py --motor 0` ist ebenfalls
standardmäßig ein Trockenlauf; der Live-Einzeltest erfordert separate Zustimmung.

Aktuelle freigegebene Sitzung: `motorpi-driving-session.service` (transient,
kein Boot-Autostart). Beenden mit `sudo systemctl stop motorpi-driving-session`:
BLE-Rampenstopp, Watchdog beenden, Simulator wieder starten. Vor dem nächsten
Sitzungsstart erneute unmittelbare Zustimmung einholen.

## Rückbau

`sudo systemctl disable --now motorpi-mobile motorpi-download motorpi-dhcp motorpi-ap`
stoppt die neuen Dienste. Für WLAN-Clientbetrieb den markierten Block
`BEGIN MOTORPI MOBILE` bis `END MOTORPI MOBILE` aus `/etc/dhcpcd.conf` entfernen.
Originalsicherung: `/etc/motorpi-mobile/dhcpcd.conf.before-mobile`; spätere
Änderungen nicht durch pauschales Zurückkopieren überschreiben. Vorherige
Watchdog- und STM32-Software wurden nicht ersetzt.
