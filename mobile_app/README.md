# MotorPi Android-App

Flutter-App mit WLAN-Steuerung (TCP zum Pi), Touch-Joystick und nativer Android-Gamecontroller-Eingabe. Start und Stopp bleiben am unteren Bildschirmrand erreichbar.

Installation, Bedienung, Protokoll, Build und Inbetriebnahme: [Dokumentation des Pi-Dienstes](../raspi/mobile/README.md).

Der ausgelieferte Pi-Dienst läuft in Simulation. Die Zuordnung der echten Motoren und ihre Vorwärtsrichtungen müssen vor der Fahrfreigabe geprüft werden.

## Architecture (since 0.4.0)

MVC-style with `provider`: views only read state and call controller
methods; all drive-safety logic lives in `DriveController`, not in widgets.

```
lib/
  main.dart          MultiProvider (VehicleLink, PiDiscovery, ShellCredentials) + MaterialApp
  theme.dart         ThemeData and AppColors; no colour literals elsewhere
  routes.dart        Named routes; each route creates and owns its controller
  app_config.dart    Debug access code, ports, fallback hosts
  models/            protocol.dart (wire format, unchanged), discovered_pi, gamepad_event
  services/          transport, vehicle_link (session), pi_discovery, log_client,
                     platform_network (bindWifi), gamepad_service
  controllers/       launcher, discovery, access_code, drive, logs, shell
  views/             one file per screen; control/ holds the drive screen, joystick, buttons
```

Flow: **Launcher** (binds the process to the WLAN) → **Discovery** (probes
the last host, `10.42.0.1` and `motorpi.local`; a probe is a short control
connection that reads the Pi's greeting without logging in, so it shows
simulation/live and whether another phone holds control) → **Access code** →
**Control**. Right after launch, a single free Pi is selected automatically.
A lost connection returns to Discovery with the reason. `VehicleLink` is
app-wide; `DriveController` exists only while the drive screen does, and
sends a stop if that screen goes away while armed.

**Debug shortcut:** `flutter run --dart-define=MOTORPI_CODE=ABCD2345` skips
the code screen in debug builds (`kDebugMode` only — release builds ignore
it). The Pi still checks the code. Never commit it.

**Tools menu (wrench icon)** on discovery, code and drive screens:

- **Logs** — read-only, from `raspi/mobile/log_server.py` (port 8081),
  authenticated with the same access code (kept in memory after a
  successful connect; asked for otherwise).
- **Shell** — full interactive SSH (`dartssh2` + `xterm`) as any user
  with password or pasted private key. Deliberately unrestricted for the
  testing phase: it can do everything that user can, including starting
  motors outside the app's safety logic. Credentials live in memory only.
  Host keys are not verified.

Opening a tool from the drive screen stops first and blocks Start (touch
and gamepad) until the tool is closed.

Tests: `flutter test` (protocol, connection, drive screen, `DriveController`,
discovery, log-client HMAC golden vector shared with the Python tests, full
launch-to-drive flow).
