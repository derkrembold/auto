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
3. Stay on the **MotorPi** WLAN and open the app. It finds the Pi on its own
   and goes straight to the drive screen — no access code (since 0.5.0, see
   below). The app binds itself to the WLAN so Android does not route the
   connection over mobile data.
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

## App 0.5.0 / protocol version 2: no access code (21.10.2026)

The access code is gone from the app, the Pi services and `install.py`:
**being on the WPA2-protected MotorPi WLAN is the admission.** The WLAN
password is now the only credential, so treat it like the old code.

- **Network check instead of a code.** The control server (8765) and the log
  service (8081) listen on every interface, including Ethernet/the home LAN,
  so both accept only peers from `allowed_networks` (config, default
  `10.42.0.0/24` and loopback; `network_policy.py`). Anyone else gets
  `E` "Only reachable from the MotorPi WLAN" (control) or no response (logs).
  Discovery over the home LAN (`motorpi.local`) therefore shows the Pi as
  unreachable on purpose; widen `allowed_networks` for LAN development.
- **Protocol version 2** (status byte 0 = 2): no challenge, no HMAC. The Pi
  greets with a status, the app claims control with one byte, commands are
  the bare 10-byte body. One phone at a time, sequence acknowledgement,
  heartbeat, limits and the state machine are unchanged. Apps up to 0.4.0
  and a v1 Pi refuse each other with "Unbekanntes Pi-Protokoll" — update
  both together (`deploy.ps1 -Install -BuildApk`).
- **Removed:** `access_code.py`, `--rotate-access-code`, the code screen,
  the `MOTORPI_CODE` debug shortcut, `key_hex` (install drops it from an
  existing config; the servers ignore it if still present) and the code line
  in `access.txt`.

What the WLAN-only model gives up, stated plainly: commands are no longer
authenticated per message — integrity and confidentiality now rest entirely
on WPA2, and any device on the MotorPi WLAN can take control while no other
phone holds it. The SSH shell is unaffected (own credentials, pinned host key).

## App 0.4.0: new screen flow, logs and shell (14.10.2026)

The app now starts with a launcher, finds the Pi on its own (short probe
connections to the last host, `10.42.0.1` and `motorpi.local`), then asks
for the access code, then shows the drive screen. Driving behaviour,
protocol and limits are unchanged. Details and the code structure:
`mobile_app/README.md`.

**Log service `log_server.py` (`motorpi-logs.service`, port 8081)** — a
separate, read-only process, so file reads and `journalctl` never touch
the control loop. Serves only a fixed list: `watchdog`, `joystick`,
`motorcontrol`, `validate_speed`, `capture_step_response`,
`validate_lin_stress` (`/home/pi/auto/*.log`) and the journals of
`motorpi-mobile`, `motorpi-driving-session`, `motorpi-ap`, `motorpi-dhcp`,
`motorpi-download`, `motorpi-logs`. Since 0.5.0 no access code: only clients
on the MotorPi WLAN are served (see above). Plain HTTP (WPA2 encrypts the
WLAN); the logs are readable by anyone on the MotorPi WLAN. Runs as `pi` with `SupplementaryGroups=systemd-journal`.
`install.py` installs and (re)starts it; it is safe next to a live session.

**Shell:** the app has a full SSH terminal (any user, password or pasted
key). Unrestricted on purpose during testing — it bypasses the app's safety
logic and the Motor Execution Consent rule in `raspi/CLAUDE.md` is up to the
person holding the phone. Nothing on the Pi changes for it; it uses the
existing SSH server.

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
  -> WLAN/TCP 10.42.0.1:8765 (WLAN-only admission, acknowledged sequence numbers)
  -> wifi_server.py -> control_core.py
  -> bridge.py (nur bei --live) -> vorhandener Watchdog -> LIN -> STM32
```

- `control_core.py`: hardware-independent state machine, control claim (one
  phone at a time), replay protection via sequence numbers, mixing, limits,
  heartbeat, shared stop ramp.
- `network_policy.py`: which peer addresses may use the control and log
  services (`allowed_networks`, default MotorPi WLAN + loopback).
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

## WLAN protocol (version 2)

TCP on port 8765 (`listen_host`/`listen_port` optional in the Pi config,
default `0.0.0.0:8765`; peers outside `allowed_networks` are rejected). Both
directions: one length byte, then the payload.

| Direction | Payload |
|---|---|
| Pi → app | `S` + 20-byte status, right after the connection is accepted, after every accepted packet, and every 200 ms |
| Pi → app | `E` + UTF-8 reason for a rejected packet (connection stays open) or connection (then closed) |
| App → Pi | 1-byte claim `0x00`, or 10-byte command |

A connection only observes until it claims control; exactly one owner at a
time. While another phone owns control, a new connection gets `E` and is
closed (discovery shows "Belegt"). Claiming twice on one connection is
refused; reconnect to start over.

Command: `<BIhhB` (little endian), 10 bytes: opcode, increasing uint32
sequence, forward/steer each -1000..1000, flags. Opcodes 1 Start, 2 Drive,
3 Stop. For Drive: bit 7 active dead-man, bits 0..6 limit 0..100 %. Start
requires neutral values and flags.

Status `<BBBBhhIHH4x`: Version, Zustand, Flags, Fehler, links/rechts Sollwert,
letzte akzeptierte Sequenz, Maximal-RPM, Heartbeat-ms, vier reservierte Bytes.
Zustände 0 gestoppt, 1 freigegeben, 2 Rampe, 3 Störung. Flags: Bit 0 live,
Bit 1 Steuerung übernommen (claimed), Bit 2 bereit. Fehler 1 Verbindung/Eingabe ausgeblieben,
3 Hardware/IPC/Überstrom, 4 Motoren/Stromsensor nicht erreichbar, 5 Motor
drehte nicht (Firmware-Stall `sys_error=-65`).

Fehler 3 bleibt gesperrt und lässt sich nicht aus der App zurücksetzen.
Fehler 4 und 5 (z. B. Motorsicherung aus) erholen sich selbst: Beide Sollwerte
sofort auf null, „bereit“ aus. Der Pi prüft alle 2 s `status` beider Motoren
und `current 0`; bei Stall sendet er `reset <motor>` (Sollwert bleibt null).
Sobald alles sauber antwortet, ist „bereit“ wieder gesetzt; weitergefahren wird
nur nach erneutem **Start** in der App. Ein Watchdog-Timeout (verspätete
Antwort) öffnet die IPC-Verbindung neu, damit keine alte Antwort als neue gilt.

A drive command counts as acknowledged only once a status with its sequence
comes back (at most 500 ms). Commands are not signed: WPA2 of the MotorPi WLAN
provides encryption and integrity, and the peer-address check keeps Ethernet/
the home LAN out. Status is readable by every WLAN client.

## Build und Deployment

Getestete Umgebung: Flutter 3.47.6 / Dart 3.13.5, JDK 17 (Temurin), Android
compile SDK 36. Flutter liegt ignoriert in `.tools/flutter` (offizielles Archiv,
SHA-256 gegen `releases_windows.json` prüfen). Packages: `provider`,
`dartssh2`, `xterm`, `shared_preferences` (`crypto` dropped in 0.5.0; see
`mobile_app/README.md`).

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

On Linux/macOS use `raspi/mobile/deploy.sh` (same steps and file list:
`--install`, `--build-apk`, `--apk <path>`, `--access-point`,
`--host user@ip`). `--logs-only` installs/restarts
just the read-only log service and, unlike a full install, is allowed while
a live driving session runs. If `motorpi.local` does not resolve, use the IP
(`--host pi@192.168.0.104` on the home LAN, or `MOTORPI_HOST`).

Bei der ersten WLAN-Einrichtung zusätzlich `-AccessPoint` angeben. Sie verlangt
den bestehenden Ethernet-Uplink. Voraussetzungen: `hostapd`, `dnsmasq`. Auf dem vorhandenen Raspbian Buster wurden die
fehlenden WLAN-Pakete über eine temporäre Quellenliste der offiziellen
Raspberry-Pi-Archive installiert; keine dauerhafte APT-Quellenänderung und kein
OS-Upgrade. Python 3.7.3 des Pi wird weiterverwendet.

Deployment: `/home/pi/auto/mobile/`, getrennt von bisherigen Watchdogdateien.
Configuration: `/etc/motorpi-mobile/config.json`. Credentials (WLAN password):
`/home/pi/auto/mobile/access.txt` (0600). Never copy passwords/keys into the
repo or the download folder.

```sh
systemctl status motorpi-mobile motorpi-logs motorpi-ap motorpi-dhcp motorpi-download
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
