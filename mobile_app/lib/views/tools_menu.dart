import 'package:flutter/material.dart';
import '../routes.dart';

/// App-bar menu for the maintenance screens (logs, shell).
class ToolsMenu extends StatelessWidget {
  const ToolsMenu({super.key, required this.host, this.beforeOpen});
  final String host;

  /// Wraps the navigation; the drive screen uses it to stop and stay
  /// disarmed while a tool covers it.
  final Future<void> Function(Future<void> Function() open)? beforeOpen;

  @override
  Widget build(BuildContext context) => PopupMenuButton<String>(
    tooltip: 'Werkzeuge',
    icon: const Icon(Icons.build_outlined),
    onSelected: (route) {
      Future<void> open() =>
          Navigator.of(context).pushNamed(route, arguments: host);
      (beforeOpen ?? (open) => open())(open);
    },
    itemBuilder: (_) => const [
      PopupMenuItem(
        value: Routes.logs,
        child: ListTile(
          leading: Icon(Icons.article_outlined),
          title: Text('Logs'),
        ),
      ),
      PopupMenuItem(
        value: Routes.shell,
        child: ListTile(leading: Icon(Icons.terminal), title: Text('Shell')),
      ),
    ],
  );
}
