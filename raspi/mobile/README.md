# MotorPi: Android-App und Raspberry-Pi-Dienst

Flutter für Android. Gesteuert wird direkt über den WLAN-Access-Point
„MotorPi“ (TCP zum Pi), über den auch SSH und der APK-Download laufen.
Ohne Internet nutzbar, kein Bluetooth mehr nötig (bis 0.2.0 lief die
Steuerung über BLE).

## Installation und Bedienung

1. Mit WLAN **MotorPi** verbinden und die Verbindung ohne Internet beibehalten.
   Das WLAN-Passwort steht in den privat bereitgestellten Zugangsdaten.
2. `http://10.42.0.1:8080/` öffnen, APK herunterladen und installieren.
   Im bisherigen LAN geht auch `http://motorpi.local:8080/`.
3. Im WLAN **MotorPi** bleiben. In der App den separaten achtstelligen
   Zugangscode eingeben und **Verbinden** antippen. Die Adresse ist mit
   `10.42.0.1` vorbelegt. Die App bindet sich selbst an das WLAN, damit
   Android die Verbindung nicht über mobile Daten leitet.
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
App-Wechsel, abgebrochene Touch-Geste, Controllertrennung und WLAN-Ausfall
beenden die Fahrt. Ein Wechsel Touch/Controller stoppt zuerst.

## Umstellung auf WLAN, App 0.3.0 (14.10.2026)

Steuerung über TCP im WLAN statt BLE. Gleiche Anmeldung, gleiche signierte
Befehle, gleiche Sequenzbestätigung, gleiche Zustandsmaschine und Limits in
`control_core.py`; nur der Transport ist neu (`wifi_server.py` statt
`ble_server.py`). Die App braucht keine Bluetooth-/Standortberechtigung mehr.
Die APK ist auf einem anderen Build-Rechner mit dessen Android-Debug-Schlüssel
signiert: Falls Android das Update ablehnt („App nicht installiert“), die alte
MotorPi-App zuerst deinstallieren. Der Zugangscode bleibt gleich.

## Stand der Auslieferung vom 14.10.2026 (BLE, 0.2.0)

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
  -> WLAN/TCP 10.42.0.1:8765 (signierte Befehle, bestätigte Sequenznummern)
  -> wifi_server.py -> control_core.py
  -> bridge.py (nur bei --live) -> vorhandener Watchdog -> LIN -> STM32
```

- `control_core.py`: Hardware-unabhängige Zustandsmaschine, HMAC-Anmeldung,
  Wiedergabeschutz, Mischung, Limits, Heartbeat, gemeinsame Stopprampe.
- `bridge.py`: ein persistenter IPC-Client des vorhandenen Watchdogs, kein
  eigener LIN-Master. Prüft vor jeder Geschwindigkeitsrunde beide Motorstatus
  und `current 0`; nicht endliche Ströme oder mehr als 15 A sperren die Fahrt,
  passend zum bestehenden Watchdog-Limit. Bei einem Fehler schließt der Client:
  Der vorhandene Watchdog stoppt dann alle bekannten Motoren.
- `wifi_server.py`: TCP-Server (nur Standardbibliothek, Python 3.7) mit
  separatem Steuerungsthread. Eine TCP-Verbindung = eine Peer-Identität.
- `install.py`, `deploy.ps1`: Installation ohne Motorstart; `-BuildApk` baut,
  testet und veröffentlicht die aktuelle App auf der Downloadseite.
- `tests/`: Logiktests, Linux-IPC mit eigenem Fake-Socket, WLAN-Transporttest
  über echte Loopback-Sockets (nur Simulation).

Normaler Stopp/Verbindungsabbruch (TCP geschlossen): proportionale Rampe beider Motoren
über 1 s. Heartbeat: fehlende gültige Befehle werden nach 0,6 s erkannt.
Wiederholtes Stopp verlängert die Rampe nicht. Die App wartet maximal 500 ms auf
eine Befehlsbestätigung und hält keine Fahrbefehle in einer Warteschlange.
Statusmeldungen kommen zusätzlich alle 200 ms.

Bei Hardware-/IPC-Fehlern wird die Störung gesperrt und der Watchdog-Client
geschlossen. Keine weiteren Rampenbefehle an einen bereits gestörten Motor.
Der Watchdog bestimmt dann den tatsächlichen Hardware-Stopp. Die App ersetzt
keinen physischen Not-Aus; Reaktionszeiten unter realer Last sind noch nicht
am Fahrzeug vermessen.

## WLAN-Protokoll (Transport für Protokoll Version 1)

TCP auf Port 8765 (`listen_host`/`listen_port` optional in der Pi-Konfiguration,
Standard `0.0.0.0:8765`). In beide Richtungen: ein Längenbyte, dann die Nutzdaten.

| Richtung | Nutzdaten |
|---|---|
| Pi → App | `C` + 16 Byte Challenge, sofort nach Verbindungsaufbau |
| Pi → App | `S` + 20 Byte Status, nach jedem angenommenen Paket und alle 200 ms |
| Pi → App | `E` + UTF-8-Begründung bei abgelehntem Paket (Verbindung bleibt) |
| App → Pi | 17 Byte Anmeldung oder 20 Byte Befehl, unverändert |

Anmeldung innerhalb 30 s: `0x00 || HMAC-SHA256(key, "auth" || nonce)[:16]`.
Pro Verbindung eigene Challenge, genau ein Besitzer der Steuerung; ein zweites
Handy erhält `E` und wird getrennt. Schlüssel: 16 Bytes. Zugangscodes bestehen
aus acht zufälligen Zeichen des Alphabets `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`
(40 Bit Entropie). Groß-/Kleinschreibung, Leerzeichen und Bindestriche sind
unerheblich. Ableitung: `SHA256("MotorPi access code v1:" + normalisierter_code)[:16]`.
Die App akzeptiert außerdem alte 32-stellige Hex-Codes für nicht umgestellte Pis.
Nach fünf falschen Anmeldungen sind weitere Versuche bis zum Ende des laufenden
30-Sekunden-Fensters blockiert, auch über neue Verbindungen hinweg.

Befehl: Body `<BIhhB` (little endian) plus
`HMAC-SHA256(key, nonce || body)[:10]`, insgesamt 20 Bytes. Body: Opcode,
steigende uint32-Sequenz, Vorwärts/Lenkung jeweils -1000..1000, Flags.
Opcodes 1 Start, 2 Fahren, 3 Stopp. Bei Fahren: Bit 7 aktive Fahrfreigabe,
Bits 0..6 Limit 0..100 %. Start verlangt neutrale Werte und Flags.

Status `<BBBBhhIHH4x`: Version, Zustand, Flags, Fehler, links/rechts Sollwert,
letzte akzeptierte Sequenz, Maximal-RPM, Heartbeat-ms, vier reservierte Bytes.
Zustände 0 gestoppt, 1 freigegeben, 2 Rampe, 3 Störung. Flags: Bit 0 live,
Bit 1 angemeldet, Bit 2 bereit. Fehler 1 Verbindung/Eingabe ausgeblieben,
3 Hardware/IPC/Überstrom, 4 Motoren/Stromsensor nicht erreichbar, 5 Motor
drehte nicht (Firmware-Stall `sys_error=-65`).

Fehler 3 bleibt gesperrt und lässt sich nicht aus der App zurücksetzen.
Fehler 4 und 5 (z. B. Motorsicherung aus) erholen sich selbst: Beide Sollwerte
sofort auf null, „bereit“ aus. Der Pi prüft alle 2 s `status` beider Motoren
und `current 0`; bei Stall sendet er `reset <motor>` (Sollwert bleibt null).
Sobald alles sauber antwortet, ist „bereit“ wieder gesetzt; weitergefahren wird
nur nach erneutem **Start** in der App. Ein Watchdog-Timeout (verspätete
Antwort) öffnet die IPC-Verbindung neu, damit keine alte Antwort als neue gilt.

Ein Fahrbefehl gilt erst als bestätigt, wenn ein Status mit seiner Sequenz
zurückkommt (maximal 500 ms). HMAC authentifiziert die Befehle; verschlüsselt
wird durch WPA2 des MotorPi-WLANs. Status ist für jeden WLAN-Teilnehmer lesbar.
Der Port ist auch über Ethernet erreichbar; ohne Zugangscode lässt sich dort
nichts steuern.

## Build und Deployment

Getestete Umgebung: Flutter 3.47.6 / Dart 3.13.5, JDK 17 (Temurin), Android
compile SDK 36. Flutter liegt ignoriert in `.tools/flutter` (offizielles Archiv,
SHA-256 gegen `releases_windows.json` prüfen). Außer `crypto` keine Pakete.

Downloadseite aktuell halten: App bauen, testen und mit Version veröffentlichen
in einem Schritt:

```powershell
.\raspi\mobile\deploy.ps1 -Install -BuildApk
```

`-BuildApk` führt `flutter pub get`, `flutter test` und
`flutter build apk --release` aus und lädt APK und `version.txt` hoch;
`install.py --app-download` setzt die Version aus `pubspec.yaml` in die
Downloadseite ein. Alternativ mit fertiger APK: `-ApkPath <apk>`.
Bekannter Windows-Stolperstein: Scheitert der Gradle-Daemon mit „Unable to
establish loopback connection“ (JDK-Unix-Socket unter 8.3-Kurzpfad im TEMP),
setzt `deploy.ps1` `JAVA_TOOL_OPTIONS=-Djdk.net.unixdomain.tmpdir=C:\Temp`.

Bei der ersten WLAN-Einrichtung zusätzlich `-AccessPoint` angeben. Sie verlangt
den bestehenden Ethernet-Uplink. Voraussetzungen: `hostapd`, `dnsmasq`. Auf dem vorhandenen Raspbian Buster wurden die
fehlenden WLAN-Pakete über eine temporäre Quellenliste der offiziellen
Raspberry-Pi-Archive installiert; keine dauerhafte APT-Quellenänderung und kein
OS-Upgrade. Python 3.7.3 des Pi wird weiterverwendet.

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
Internetweiterleitung. Neue Dienste starten beim Booten; der Steuerdienst bleibt
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
Watchdog in einer freigegebenen Live-Sitzung starten und den WLAN-Dienst interaktiv
mit `--live` ausführen. Er startet mit null und verlangt zusätzlich Start plus
aktive Fahrfreigabe aus der App. Nicht parallel mit `joystick.py` oder
`motorcontrol.py` verbinden. Die installierte Systemd-Unit bleibt ohne `--live`.

`live_session.py` ist ein vorbereiteter Sitzungsstarter, standardmäßig ohne
Ausführung. Nur mit unmittelbarer menschlicher Zustimmung werden `--live`
und `--consent STARTFAHRT` verwendet. Er prüft die verifizierte Konfiguration,
stoppt den Simulator, startet Watchdog und WLAN-Dienst als zusammengehörige
Sitzung und stellt beim Ende Simulation wieder her. Keine Live-Autostarts oder
automatischen Neustarts nach Störungen. `commission.py --motor 0` ist ebenfalls
standardmäßig ein Trockenlauf; der Live-Einzeltest erfordert separate Zustimmung.

Aktuelle freigegebene Sitzung: `motorpi-driving-session.service` (transient,
kein Boot-Autostart). Beenden mit `sudo systemctl stop motorpi-driving-session`:
Rampenstopp, Watchdog beenden, Simulator wieder starten. Vor dem nächsten
Sitzungsstart erneute unmittelbare Zustimmung einholen.

## Rückbau

`sudo systemctl disable --now motorpi-mobile motorpi-download motorpi-dhcp motorpi-ap`
stoppt die neuen Dienste. Für WLAN-Clientbetrieb den markierten Block
`BEGIN MOTORPI MOBILE` bis `END MOTORPI MOBILE` aus `/etc/dhcpcd.conf` entfernen.
Originalsicherung: `/etc/motorpi-mobile/dhcpcd.conf.before-mobile`; spätere
Änderungen nicht durch pauschales Zurückkopieren überschreiben. Vorherige
Watchdog- und STM32-Software wurden nicht ersetzt.
