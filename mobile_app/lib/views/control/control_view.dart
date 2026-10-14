import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../controllers/drive_controller.dart';
import '../../models/protocol.dart';
import '../../routes.dart';
import '../../services/vehicle_link.dart';
import '../../theme.dart';
import '../tools_menu.dart';
import 'drive_buttons.dart';
import 'joystick.dart';

class ControlView extends StatefulWidget {
  const ControlView({super.key});
  @override
  State<ControlView> createState() => _ControlViewState();
}

class _ControlViewState extends State<ControlView> {
  late final VehicleLink _link;
  bool _leaving = false;

  @override
  void initState() {
    super.initState();
    _link = context.read<VehicleLink>();
    _link.addListener(_onLink);
  }

  /// A lost or closed session leaves the drive screen; discovery shows why.
  void _onLink() {
    if (_link.connected || _link.connecting || _leaving) return;
    _leaving = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        Navigator.of(
          context,
        ).pushNamedAndRemoveUntil(Routes.discovery, (_) => false);
      }
    });
  }

  Future<void> _disconnect() async {
    await context.read<DriveController>().stop();
    await _link.disconnect();
  }

  @override
  void dispose() {
    _link.removeListener(_onLink);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final link = context.watch<VehicleLink>();
    final drive = context.read<DriveController>();
    return Scaffold(
      bottomNavigationBar: link.connected
          ? const SafeArea(
              child: Padding(
                padding: EdgeInsets.all(16),
                child: DriveButtons(),
              ),
            )
          : null,
      appBar: AppBar(
        title: const Text('MotorPi'),
        actions: [
          Chip(
            label: Text(
              !link.connected
                  ? 'OFFLINE'
                  : link.status?.live == true
                  ? 'ECHTBETRIEB'
                  : 'SIMULATION',
            ),
          ),
          ToolsMenu(
            host: link.host ?? defaultHost,
            beforeOpen: (open) => drive.suspendWhile(open),
          ),
        ],
      ),
      body: SafeArea(
        child: link.connected
            ? _DrivingPanel(onDisconnect: _disconnect)
            : const SizedBox.shrink(),
      ),
    );
  }
}

class _DrivingPanel extends StatelessWidget {
  const _DrivingPanel({required this.onDisconnect});
  final Future<void> Function() onDisconnect;

  @override
  Widget build(BuildContext context) {
    final link = context.watch<VehicleLink>();
    final drive = context.watch<DriveController>();
    final status = link.status;
    final limitText = '${(drive.limit * 100).round()}%';
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
                  if (status?.problem != null)
                    Text(
                      status!.problem!,
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: AppColors.warning),
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
                          onSelected: drive.setUseGamepad,
                          itemBuilder: (_) => const [
                            PopupMenuItem(value: false, child: Text('Touch')),
                            PopupMenuItem(
                              value: true,
                              child: Text('Controller'),
                            ),
                          ],
                          child: Text(
                            drive.useGamepad ? 'Controller ▾' : 'Touch ▾',
                          ),
                        ),
                        const Spacer(),
                        PopupMenuButton<double>(
                          enabled: !drive.armed,
                          tooltip: 'Geschwindigkeitslimit',
                          onSelected: drive.setLimit,
                          itemBuilder: (_) => [
                            for (final value in [.5, .6, .7, .8, .9, 1.0])
                              PopupMenuItem(
                                value: value,
                                child: Text('${(value * 100).round()}%'),
                              ),
                          ],
                          child: Text('Limit $limitText ▾'),
                        ),
                        IconButton(
                          tooltip: 'Verbindung trennen',
                          onPressed: onDisconnect,
                          icon: const Icon(Icons.link_off),
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
                      selected: {drive.useGamepad},
                      onSelectionChanged: (choice) =>
                          drive.setUseGamepad(choice.first),
                    ),
                  Expanded(
                    child: LayoutBuilder(
                      builder: (context, constraints) {
                        final size = constraints.biggest.shortestSide.clamp(
                          0.0,
                          250.0,
                        );
                        return Center(
                          child: drive.useGamepad
                              ? Column(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Text(drive.controllerName),
                                    const Text(
                                      'A: Start · Linker Stick: Fahren / Lenken\n'
                                      'B: Stopp · Letzte Stellung bleibt aktiv',
                                      textAlign: TextAlign.center,
                                    ),
                                  ],
                                )
                              : Joystick(
                                  enabled: drive.armed && !drive.stopping,
                                  size: size,
                                  onChanged: drive.setJoystick,
                                ),
                        );
                      },
                    ),
                  ),
                  Text(
                    drive.useGamepad
                        ? 'Letzte Stickstellung bleibt aktiv. B: Stopp.'
                        : 'Joystick bleibt stehen. STOPP beendet die Fahrt.',
                    textAlign: TextAlign.center,
                  ),
                  if (!compact) ...[
                    Text('Geschwindigkeitslimit: $limitText'),
                    SizedBox(
                      height: 40,
                      child: Slider(
                        value: drive.limit,
                        min: .5,
                        max: 1,
                        divisions: 5,
                        onChanged: drive.armed ? null : drive.setLimit,
                      ),
                    ),
                    const Text(
                      'Verbindungsabbruch / App-Wechsel: Sicherheitsstopp.',
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 12, color: AppColors.muted),
                    ),
                    TextButton(
                      onPressed: onDisconnect,
                      child: const Text('Verbindung trennen'),
                    ),
                  ],
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}
