import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'vehicle_link.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const MotorPiApp());
}

class MotorPiApp extends StatelessWidget {
  const MotorPiApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'MotorPi',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      colorScheme: ColorScheme.fromSeed(
        seedColor: const Color(0xff67e5b0),
        brightness: Brightness.dark,
      ),
      scaffoldBackgroundColor: const Color(0xff101817),
    ),
    home: const ControlScreen(),
  );
}

class ControlScreen extends StatefulWidget {
  const ControlScreen({super.key, this.link});
  final VehicleLink? link;
  @override
  State<ControlScreen> createState() => _ControlScreenState();
}

class _ControlScreenState extends State<ControlScreen>
    with WidgetsBindingObserver {
  late final VehicleLink link;
  final accessCode = TextEditingController();
  Timer? timer;
  StreamSubscription<dynamic>? gamepad;
  bool armed = false, held = false, useGamepad = false, stopping = false;
  double forward = 0, steer = 0, limit = 0.6;
  String controllerName = 'Kein Controller';

  @override
  void initState() {
    super.initState();
    link = widget.link ?? VehicleLink();
    WidgetsBinding.instance.addObserver(this);
    link.addListener(_refresh);
    gamepad = const EventChannel('motorpi/gamepad')
        .receiveBroadcastStream()
        .listen(
          _gamepad,
          onError: (Object _) {
            if (useGamepad) unawaited(stop());
          },
        );
    timer = Timer.periodic(const Duration(milliseconds: 100), (_) => _tick());
  }

  void _refresh() {
    if (!mounted) return;
    if (!link.connected || link.status?.state != 1) {
      armed = false;
      held = false;
      forward = steer = 0;
    }
    setState(() {});
  }

  void _input(double f, double s, bool active) {
    final wasHeld = held;
    setState(() {
      forward = f;
      steer = s;
      held = active;
    });
    if (!active && wasHeld && armed) unawaited(stop());
  }

  void _gamepad(dynamic event) {
    if (!mounted) return;
    final data = Map<String, dynamic>.from(event as Map);
    setState(
      () => controllerName = data['name'] as String? ?? 'Kein Controller',
    );
    if (!useGamepad) return;
    if (data['stop'] == true || data['connected'] == false) {
      unawaited(stop());
      return;
    }
    final f = (data['forward'] as num? ?? 0).toDouble();
    final s = (data['steer'] as num? ?? 0).toDouble();
    if (data['start'] == true && f.abs() < .08 && s.abs() < .08) {
      unawaited(start());
      return;
    }
    // A spring-centred controller retains the last non-neutral setpoint too.
    if (armed && (f.abs() >= .08 || s.abs() >= .08)) _input(f, s, true);
  }

  Future<void> start() async {
    if (held ||
        forward.abs() > .08 ||
        steer.abs() > .08 ||
        stopping ||
        link.status?.ready != true) {
      return;
    }
    final ok = await link.send(1);
    if (mounted && ok && !stopping && link.connected) {
      setState(() => armed = true);
    }
  }

  Future<void> stop() async {
    if (!mounted || stopping) return;
    setState(() {
      armed = false;
      held = false;
      forward = steer = 0;
      stopping = true;
    });
    // Do not queue drive packets behind a stalled radio. Stop follows at most one in-flight write.
    final deadline = DateTime.now().add(const Duration(milliseconds: 550));
    while (link.busy && DateTime.now().isBefore(deadline)) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }
    if (link.connected && (link.busy || !await link.send(3))) {
      await link.disconnect();
    }
    if (mounted) setState(() => stopping = false);
  }

  void _tick() {
    if (!armed || !link.connected || stopping) return;
    final now = DateTime.now();
    if (link.lastStatus == null ||
        now.difference(link.lastStatus!).inMilliseconds > 1000) {
      unawaited(stop());
      return;
    }
    unawaited(
      link.send(
        2,
        forward: (forward * 1000).round(),
        steer: (steer * 1000).round(),
        held: held,
        speedLimit: (limit * 100).round(),
      ),
    );
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) unawaited(stop());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    timer?.cancel();
    unawaited(gamepad?.cancel());
    link.removeListener(_refresh);
    link.dispose();
    accessCode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final status = link.status;
    return Scaffold(
      bottomNavigationBar: link.connected
          ? SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: _buttons(),
              ),
            )
          : null,
      appBar: AppBar(
        title: const Text('MotorPi'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: Chip(
              label: Text(
                !link.connected
                    ? 'OFFLINE'
                    : status?.live == true
                    ? 'ECHTBETRIEB'
                    : 'SIMULATION',
              ),
            ),
          ),
        ],
      ),
      body: SafeArea(
        child: link.connected
            ? _drivingPanel()
            : SingleChildScrollView(
                child: Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 640),
                    child: Padding(
                      padding: const EdgeInsets.all(20),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Text(
                            status?.label ?? 'Dein Fahrzeug. In deiner Hand.',
                            style: Theme.of(context).textTheme.headlineSmall,
                          ),
                          const SizedBox(height: 8),
                          Text(link.message),
                          const SizedBox(height: 20),
                          if (!link.connected) ...[
                            TextField(
                              controller: accessCode,
                              autocorrect: false,
                              enableSuggestions: false,
                              decoration: const InputDecoration(
                                labelText: 'Persönlicher Zugangscode',
                                hintText: '8 Zeichen aus der Pi-Einrichtung',
                                border: OutlineInputBorder(),
                              ),
                            ),
                            const SizedBox(height: 12),
                            FilledButton.tonalIcon(
                              onPressed: link.connecting ? null : link.scan,
                              icon: const Icon(Icons.bluetooth_searching),
                              label: Text(
                                link.scanning
                                    ? 'Erneut suchen'
                                    : 'MotorPi suchen',
                              ),
                            ),
                            for (final device in link.devices.values)
                              Card(
                                child: ListTile(
                                  leading: const Icon(Icons.directions_car),
                                  title: Text(
                                    device.name.isEmpty
                                        ? 'MotorPi'
                                        : device.name,
                                  ),
                                  subtitle: Text(device.id),
                                  trailing: const Icon(Icons.chevron_right),
                                  onTap: link.connecting
                                      ? null
                                      : () => link.connect(
                                          device,
                                          accessCode.text,
                                        ),
                                ),
                              ),
                            if (link.connecting)
                              const LinearProgressIndicator(),
                            const SizedBox(height: 20),
                            const Text(
                              'Bluetooth steuert das Fahrzeug. Das WLAN „MotorPi“ ist zusätzlich für den lokalen Zugang verfügbar.',
                            ),
                          ],
                        ],
                      ),
                    ),
                  ),
                ),
              ),
      ),
    );
  }

  Widget _drivingPanel() {
    final status = link.status;
    return LayoutBuilder(
      builder: (context, available) {
        final compact = available.maxHeight < 400;
        return Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 640),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    status?.label ?? link.message,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  if (status?.error != 0)
                    const Text(
                      'Steuerung gestoppt. Pi und Verbindung prüfen.',
                      style: TextStyle(color: Colors.orange),
                    ),
                  Row(
                    children: [
                      Expanded(
                        child: Text('Links: ${status?.left ?? 0} U/min'),
                      ),
                      Expanded(
                        child: Text('Rechts: ${status?.right ?? 0} U/min'),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  if (compact)
                    Row(
                      children: [
                        PopupMenuButton<bool>(
                          tooltip: 'Eingabe auswählen',
                          onSelected: (choice) async {
                            await stop();
                            if (mounted) setState(() => useGamepad = choice);
                          },
                          itemBuilder: (_) => const [
                            PopupMenuItem(value: false, child: Text('Touch')),
                            PopupMenuItem(
                              value: true,
                              child: Text('Controller'),
                            ),
                          ],
                          child: Text(useGamepad ? 'Controller ▾' : 'Touch ▾'),
                        ),
                        const Spacer(),
                        PopupMenuButton<double>(
                          enabled: !armed,
                          tooltip: 'Geschwindigkeitslimit',
                          onSelected: (value) => setState(() => limit = value),
                          itemBuilder: (_) => [
                            for (final value in [.5, .6, .7, .8, .9, 1.0])
                              PopupMenuItem(
                                value: value,
                                child: Text('${(value * 100).round()}%'),
                              ),
                          ],
                          child: Text('Limit ${(limit * 100).round()}% ▾'),
                        ),
                        IconButton(
                          tooltip: 'Verbindung trennen',
                          onPressed: () async {
                            await stop();
                            await link.disconnect();
                          },
                          icon: const Icon(Icons.bluetooth_disabled),
                        ),
                      ],
                    )
                  else
                    SegmentedButton<bool>(
                      segments: const [
                        ButtonSegment(
                          value: false,
                          label: Text('Touch'),
                          icon: Icon(Icons.touch_app),
                        ),
                        ButtonSegment(
                          value: true,
                          label: Text('Controller'),
                          icon: Icon(Icons.sports_esports),
                        ),
                      ],
                      selected: {useGamepad},
                      onSelectionChanged: (choice) async {
                        await stop();
                        if (mounted) setState(() => useGamepad = choice.first);
                      },
                    ),
                  Expanded(
                    child: LayoutBuilder(
                      builder: (context, constraints) {
                        final size = constraints.biggest.shortestSide.clamp(
                          0.0,
                          250.0,
                        );
                        return Center(
                          child: useGamepad
                              ? Column(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Text(controllerName),
                                    const Text(
                                      'A: Start · Linker Stick: Fahren / Lenken\n'
                                      'B: Stopp · Letzte Stellung bleibt aktiv',
                                      textAlign: TextAlign.center,
                                    ),
                                  ],
                                )
                              : Joystick(
                                  enabled: armed && !stopping,
                                  size: size,
                                  onChanged: _input,
                                ),
                        );
                      },
                    ),
                  ),
                  Text(
                    useGamepad
                        ? 'Letzte Stickstellung bleibt aktiv. B: Stopp.'
                        : 'Joystick bleibt stehen. STOPP beendet die Fahrt.',
                    textAlign: TextAlign.center,
                  ),
                  if (!compact)
                    Text('Geschwindigkeitslimit: ${(limit * 100).round()}%'),
                  if (!compact)
                    SizedBox(
                      height: 40,
                      child: Slider(
                        value: limit,
                        min: .5,
                        max: 1,
                        divisions: 5,
                        onChanged: armed
                            ? null
                            : (value) => setState(() => limit = value),
                      ),
                    ),
                  if (!compact)
                    const Text(
                      'Verbindungsabbruch / App-Wechsel: Sicherheitsstopp.',
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 12, color: Colors.white60),
                    ),
                  if (!compact)
                    TextButton(
                      onPressed: () async {
                        await stop();
                        await link.disconnect();
                      },
                      child: const Text('Verbindung trennen'),
                    ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buttons() => Row(
    children: [
      Expanded(
        child: FilledButton.icon(
          onPressed:
              armed ||
                  stopping ||
                  held ||
                  link.status?.ready != true ||
                  link.status?.state == 2 ||
                  link.status?.state == 3
              ? null
              : start,
          icon: const Icon(Icons.play_arrow),
          label: const Text('START'),
        ),
      ),
      const SizedBox(width: 12),
      Expanded(
        child: FilledButton.icon(
          style: FilledButton.styleFrom(
            backgroundColor: const Color(0xffbf3e39),
            foregroundColor: Colors.white,
            padding: const EdgeInsets.symmetric(vertical: 20),
          ),
          onPressed: stop,
          icon: const Icon(Icons.stop),
          label: const Text('STOPP'),
        ),
      ),
    ],
  );
}

class Joystick extends StatefulWidget {
  const Joystick({
    super.key,
    required this.enabled,
    required this.onChanged,
    this.size = 250,
  });
  final bool enabled;
  final double size;
  final void Function(double forward, double steer, bool held) onChanged;
  @override
  State<Joystick> createState() => _JoystickState();
}

class _JoystickState extends State<Joystick> {
  Offset offset = Offset.zero;
  int? pointer;
  void cancel() {
    pointer = null;
    setState(() => offset = Offset.zero);
    widget.onChanged(0, 0, false);
  }

  void update(PointerEvent event) {
    if (!widget.enabled || event.pointer != pointer) return;
    if (widget.size <= 0) return;
    final radius = widget.size * .36;
    var next = event.localPosition - Offset(widget.size / 2, widget.size / 2);
    if (next.distance > radius) next = next / next.distance * radius;
    setState(() => offset = next);
    widget.onChanged(-next.dy / radius, next.dx / radius, true);
  }

  @override
  void didUpdateWidget(Joystick oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.enabled) {
      pointer = null;
      offset = Offset.zero;
    }
  }

  @override
  Widget build(BuildContext context) => Listener(
    onPointerDown: (event) {
      if (widget.enabled && pointer == null) {
        pointer = event.pointer;
        update(event);
      }
    },
    onPointerMove: update,
    onPointerUp: (event) {
      // Keep the visible setpoint and heartbeats until STOPP or a safety stop.
      if (event.pointer == pointer) pointer = null;
    },
    onPointerCancel: (event) {
      if (event.pointer == pointer) cancel();
    },
    child: SizedBox(
      width: widget.size,
      height: widget.size,
      child: CustomPaint(painter: _StickPainter(offset, widget.enabled)),
    ),
  );
}

class _StickPainter extends CustomPainter {
  _StickPainter(this.offset, this.enabled);
  final Offset offset;
  final bool enabled;
  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    final scale = size.width / 250;
    canvas.scale(scale);
    size = const Size(250, 250);
    final center = size.center(Offset.zero);
    canvas.drawCircle(center, 112, Paint()..color = const Color(0xff1c2b27));
    final lines = Paint()
      ..color = const Color(0xff3d5149)
      ..strokeWidth = 1;
    canvas.drawLine(
      center - const Offset(95, 0),
      center + const Offset(95, 0),
      lines,
    );
    canvas.drawLine(
      center - const Offset(0, 95),
      center + const Offset(0, 95),
      lines,
    );
    canvas.drawCircle(center, 70, lines..style = PaintingStyle.stroke);
    canvas.drawCircle(
      center + (scale > 0 ? offset / scale : Offset.zero),
      33,
      Paint()
        ..color = enabled ? const Color(0xff67e5b0) : const Color(0xff66766e),
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(_StickPainter oldDelegate) =>
      offset != oldDelegate.offset || enabled != oldDelegate.enabled;
}
