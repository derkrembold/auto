import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'controllers/shell_controller.dart';
import 'routes.dart';
import 'services/known_hosts.dart';
import 'services/pi_discovery.dart';
import 'services/vehicle_link.dart';
import 'theme.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(
    MultiProvider(
      providers: [
        // App-wide: the session survives screen changes; drive state does not.
        ChangeNotifierProvider(create: (_) => VehicleLink()),
        Provider(create: (_) => PiDiscovery()),
        Provider(create: (_) => ShellCredentials()),
        Provider<KnownHosts>(create: (_) => StoredKnownHosts()),
      ],
      child: const MotorPiApp(),
    ),
  );
}

class MotorPiApp extends StatelessWidget {
  const MotorPiApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'MotorPi',
    debugShowCheckedModeBanner: false,
    theme: buildTheme(),
    initialRoute: Routes.launcher,
    onGenerateRoute: Routes.onGenerateRoute,
  );
}
