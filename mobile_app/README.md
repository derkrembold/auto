# MotorPi Android-App

Flutter-App mit WLAN-Steuerung (TCP zum Pi), Touch-Joystick und nativer Android-Gamecontroller-Eingabe. Start und Stopp bleiben am unteren Bildschirmrand erreichbar.

Installation, Bedienung, Protokoll, Build und Inbetriebnahme: [Dokumentation des Pi-Dienstes](../raspi/mobile/README.md).

Der ausgelieferte Pi-Dienst läuft in Simulation. Die Zuordnung der echten Motoren und ihre Vorwärtsrichtungen müssen vor der Fahrfreigabe geprüft werden.

## Architecture (since 0.4.0)

MVC-style with `provider`: views only read state and call controller
methods; all drive-safety logic lives in `DriveController`, not in widgets.

```
lib/
  main.dart          MultiProvider (VehicleLink, PiDiscovery, ShellCredentials, KnownHosts) + MaterialApp
  theme.dart         ThemeData and AppColors; no colour literals elsewhere
  routes.dart        Named routes; each route creates and owns its controller
  app_config.dart    Ports, fallback hosts
  models/            protocol.dart (wire format, version 2), discovered_pi, gamepad_event
  services/          transport, vehicle_link (session), pi_discovery, log_client,
                     platform_network (bindWifi), gamepad_service, known_hosts
  controllers/       launcher, discovery, drive, logs, shell
  views/             one file per screen; control/ holds the drive screen, joystick, buttons
```

Flow: **Launcher** (binds the process to the WLAN) → **Discovery** (probes
the last host, `10.42.0.1` and `motorpi.local`; a probe is a short control
connection that reads the Pi's greeting without claiming control, so it
shows simulation/live and whether another phone holds control) → **Control**.
There is no access code since 0.5.0: being on the MotorPi WLAN is the
admission, and the Pi refuses peers from elsewhere (see the Pi README's
"App 0.5.0" section). Selecting a Pi claims control right away; a refusal
keeps the user on Discovery with the reason. Right after launch, a single
free Pi is selected automatically.
A lost connection returns to Discovery with the reason. `VehicleLink` is
app-wide; `DriveController` exists only while the drive screen does, and
sends a stop if that screen goes away while armed.

**Tools menu (wrench icon)** on discovery and drive screens:

- **Logs** — read-only, from `raspi/mobile/log_server.py` (port 8081),
  no access code; only served on the MotorPi WLAN.
- **Shell** — full interactive SSH (`dartssh2` + `xterm`) as any user
  with password or pasted private key. Deliberately unrestricted for the
  testing phase: it can do everything that user can, including starting
  motors outside the app's safety logic. Credentials live in memory only.
  The Pi's host key is pinned on first use: the first connect shows its
  SHA-256 fingerprint to compare with `ssh-keygen -lf
  /etc/ssh/ssh_host_ed25519_key.pub` on the Pi, and the confirmed key is
  stored per host name (`shared_preferences`). A different key is refused
  before any password or private key is used; after re-imaging a Pi, use
  "Schlüssel vergessen" to confirm the new one.

Opening a tool from the drive screen stops first and blocks Start (touch
and gamepad) until the tool is closed.

Tests: `flutter test` (protocol, connection, drive screen, `DriveController`,
discovery, log client, drive-packet golden vector shared with the Python
tests, SSH host key pinning, full launch-to-drive flow).
