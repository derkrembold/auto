import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'controllers/discovery_controller.dart';
import 'controllers/drive_controller.dart';
import 'controllers/launcher_controller.dart';
import 'controllers/logs_controller.dart';
import 'controllers/shell_controller.dart';
import 'models/protocol.dart';
import 'services/known_hosts.dart';
import 'services/pi_discovery.dart';
import 'services/vehicle_link.dart';
import 'views/control/control_view.dart';
import 'views/discovery_view.dart';
import 'views/launcher_view.dart';
import 'views/logs_view.dart';
import 'views/shell_view.dart';

/// Launcher -> discovery -> control; no access code, the MotorPi WLAN is the
/// admission. Logs and shell are reachable from discovery and control.
/// Each route owns its controller, so leaving a screen disposes its timers.
abstract final class Routes {
  static const launcher = '/';

  /// Argument: `true` right after launch to continue automatically when
  /// exactly one free Pi is found.
  static const discovery = '/discovery';

  static const control = '/control';

  /// Argument for logs and shell: the host (defaults to the connected Pi).
  static const logs = '/logs';
  static const shell = '/shell';

  static Route<dynamic> onGenerateRoute(RouteSettings settings) {
    final argument = settings.arguments;
    Widget page(BuildContext context) => switch (settings.name) {
      launcher => ChangeNotifierProvider(
        create: (_) => LauncherController(),
        child: const LauncherView(),
      ),
      discovery => ChangeNotifierProvider(
        create: (context) => DiscoveryController(
          discovery: context.read<PiDiscovery>(),
          link: context.read<VehicleLink>(),
          autoSelect: argument == true,
        ),
        child: const DiscoveryView(),
      ),
      control => ChangeNotifierProvider(
        create: (context) => DriveController(link: context.read<VehicleLink>()),
        child: const ControlView(),
      ),
      logs => ChangeNotifierProvider(
        create: (context) => LogsController(
          host:
              argument as String? ??
              context.read<VehicleLink>().host ??
              defaultHost,
        ),
        child: const LogsView(),
      ),
      shell => ChangeNotifierProvider(
        create: (context) => ShellController(
          host:
              argument as String? ??
              context.read<VehicleLink>().host ??
              defaultHost,
          credentials: context.read<ShellCredentials>(),
          knownHosts: context.read<KnownHosts>(),
        ),
        child: const ShellView(),
      ),
      _ => Scaffold(
        body: Center(child: Text('Unbekannte Seite ${settings.name}')),
      ),
    };
    return MaterialPageRoute(settings: settings, builder: page);
  }
}
