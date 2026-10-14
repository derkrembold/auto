# Prüfung der ersten Auslieferung, 07.10.2026

- 12 Python-Tests erfolgreich: Authentifizierung, manipulierte/wiederholte
  Befehle, Sitzungsbesitz, Startfreigabe, Rampen, Loslassen, Heartbeat,
  Fehlerverriegelung, Motorzuordnung und Geschwindigkeitslimit beim Lenken.
- 6 Flutter-Tests erfolgreich: gemeinsamer HMAC-Testvektor Python/Dart,
  Eingabe-/Statusvalidierung, Touch-Loslassen/-Abbruch, deaktivierter Joystick,
  erreichbarer Stopp bei 360 × 640 und Stopp beim App-Wechsel.
- `flutter analyze` ohne Befunde; Android-Release-APK gebaut, im API-36-Emulator
  installiert und gestartet. Oberfläche und Android-Berechtigungsdialog für
  Geräte in der Nähe geprüft.
- Echter BLE-Funkweg vom Windows-Laptop zum Pi: Discovery, Ablehnung falschen
  Zugangscodes, Anmeldung, 20-Byte-Befehle, bestätigte Sequenzen, Notifications,
  beide simulierten Motorsollwerte, Stopprampe, Heartbeat-Verlust und physische
  BLE-Trennung erfolgreich. Windows hält die physische Verbindung nach dem
  Schließen des GATT-Clients noch kurz offen; der Test berücksichtigt das.
- Echter Unix-Socket auf dem Pi zu einem **privaten Fake-Watchdog**: Befehle für
  beide Instanzen, Statusprüfung und Verbindungsschluss bei simuliertem Stall
  erfolgreich. Der echte Motor-Socket wurde nicht geöffnet.
- `motorpi-mobile`, `motorpi-ap`, `motorpi-dhcp`, `motorpi-download` aktiv und
  für Boot aktiviert. WLAN-Interface UP mit `10.42.0.1/24`.
- Downloadseite und APK über Port 8080 erreichbar; lokale und entfernte
  APK-Prüfsumme identisch. `/tmp/motorwatchdog.sock` ist nicht vorhanden;
  BLE-Server meldet ausdrücklich SIMULATION.

APK: `MotorPi-0.1.0.apk`, 49.714.243 Bytes.
SHA-256: `0ca4ad8897b7ff3d39f8143763d06b7bc1b2d838f7e6bc663f55364c9bfbffc6`.

Noch nicht geprüft: reales Android-Handy mit Bluetooth-Funkverbindung,
vorhandenes Gamecontroller-Modell, WLAN-Beitritt des Handys, Motorinstanzen und
Drehrichtungen, Hardwarefahrbetrieb und Reaktionszeiten unter Last. Der Pi
bleibt bis zur abgesprochenen Inbetriebnahme in Simulation.

## Verbindungsupdate 0.1.1, 07.10.2026

Auf dem Handy wurde ein Timeout nach exakt 3 s gemeldet. Die erste Version
teilte dieses kurze Zeitlimit mit der impliziten Android-Dienstsuche und startete
Status-Abonnement und Anmeldung gleichzeitig. 0.1.1 trennt diese Schritte,
wartet auf die erste Statusmeldung vor dem Schreiben der Anmeldung und auf die
Anmeldebestätigung aus dem Pi. Ein Abbruch wird mit seinem konkreten Schritt
gemeldet. Veraltete Verbindungsversuche dürfen keine neue Sitzung beenden.

Vier zusätzliche Verbindungsregressionen bestehen: Dienstsuche über 3 s,
verzögerte Authentifizierungsbestätigung, konkrete Timeout-Meldung und Abbruch
während der Dienstsuche. Der BLE-Test wurde auf die neue Reihenfolge angepasst
und besteht über den echten Funkweg Laptop/Pi einschließlich Stopps. Ein erster
Laptop-Versuch brach während der Dienstsuche ab; der aufgezeichnete Wiederholungs-
versuch bestand vollständig. Erfolg auf dem betroffenen Handy ist nach dem
APK-Update noch vom Nutzer zu bestätigen. Schlüssel bleiben unverändert.

## App 0.2.0 und freigegebene Live-Sitzung, 14.10.2026

- Fester Fahrbildschirm ohne Scrollcontainer: Touch-Drag bleibt in Hochformat
  360×640 und Querformat 640×360 im gleichen Bildschirmbereich; Start/Stopp
  erreichbar, keine Layoutfehler. Loslassen behält die Fahrt bei, Stopp beendet
  weitere Fahrpakete. App-Wechsel stoppt weiterhin. Flutter analyze fehlerfrei;
  13 Flutter-Tests einschließlich bestehender BLE-Verbindungsregressionen.
- Achtstelliger Zufallscode; gleiche SHA-256-Schlüsselableitung in Python/Dart
  mit unabhängiger Referenz geprüft. Authentifizierungsfehlerlimit gilt auch
  bei wechselnden Peer-Adressen. Alter Code wurde auf dem Pi ersetzt, private
  Zugangsdaten außerhalb des Repository aktualisiert.
- 18 Python-Tests: Protokoll, Stopps, Vorzeichen, Zugangscodes und isolierter
  Zuordnungstest. Alle bestehen; Sitzungsskripte standardmäßig Trockenlauf.
- Einzelner, unmittelbar freigegebener Realtest: Motor 0 bei +600 U/min für
  eine Sekunde, positive Richtung vom Nutzer als links/vorwärts bestätigt.
  RPM-Rückmeldung 600, gestufter Rampenstopp, beide Sollwerte danach null.
  Motor 1 wurde auf Wunsch nicht erneut getestet.
- Vorhandene Pi-Startbefehle enthalten links 0/cw, rechts 1/ccw. Der Nutzer
  bestätigte diese Übernahme und den unmittelbaren Live-Sitzungsstart separat.
  Watchdog und BLE-Dienst in LIVE aktiv, Status beider Motoren ret=0/sys_error=0,
  Stromsensor lesbar, beide Sollwerte initial null. Keine automatische Fahrt.
- APK 0.2.0/versionCode 3: Download HTTP 200, Pi-/Laptop-Prüfsummen identisch:
  `099ba3f4757d8c26a8bda4b1243ff81758c06ac3217516d25b78e48245e33aeb`.
- Ein neuer Funk-Smoke-Test vom Laptop konnte MotorPi während des Scans nicht
  finden. Deshalb kein neuer erfolgreicher Laptop-BLE-Test behauptet. Anmeldung
  mit neuem Code und Fahren auf dem tatsächlichen Handy sind noch zu bestätigen.
- Sitzung läuft als transienter Dienst `motorpi-driving-session`, ohne Neustart
  nach Fehlern oder Live-Boot-Autostart. Beim Beenden wird Simulation wiederhergestellt.
