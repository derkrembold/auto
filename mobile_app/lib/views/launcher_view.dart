import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../controllers/launcher_controller.dart';
import '../routes.dart';

class LauncherView extends StatefulWidget {
  const LauncherView({super.key});
  @override
  State<LauncherView> createState() => _LauncherViewState();
}

class _LauncherViewState extends State<LauncherView> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _prepare());
  }

  Future<void> _prepare() async {
    if (await context.read<LauncherController>().prepare()) _continue();
  }

  void _continue() {
    if (!mounted) return;
    Navigator.of(
      context,
    ).pushReplacementNamed(Routes.discovery, arguments: true);
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<LauncherController>();
    final text = Theme.of(context).textTheme;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(
                  Icons.electric_car,
                  size: 72,
                  color: Theme.of(context).colorScheme.primary,
                ),
                const SizedBox(height: 16),
                Text('MotorPi', style: text.headlineMedium),
                const SizedBox(height: 4),
                const Text('Dein Fahrzeug. In deiner Hand.'),
                const SizedBox(height: 32),
                if (controller.error == null)
                  const CircularProgressIndicator()
                else ...[
                  Text(controller.error!, textAlign: TextAlign.center),
                  const SizedBox(height: 16),
                  FilledButton.tonalIcon(
                    onPressed: controller.busy ? null : _prepare,
                    icon: const Icon(Icons.wifi),
                    label: const Text('Erneut versuchen'),
                  ),
                  TextButton(
                    onPressed: _continue,
                    child: const Text('Trotzdem weiter'),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
