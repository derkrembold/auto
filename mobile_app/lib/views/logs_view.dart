import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../app_config.dart';
import '../controllers/logs_controller.dart';
import '../theme.dart';

class LogsView extends StatefulWidget {
  const LogsView({super.key});
  @override
  State<LogsView> createState() => _LogsViewState();
}

class _LogsViewState extends State<LogsView> {
  @override
  void initState() {
    super.initState();
    context.read<LogsController>().loadSources();
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<LogsController>();
    return Scaffold(
      appBar: AppBar(
        title: Text('Logs · ${controller.host}'),
        actions: [
          IconButton(
            tooltip: 'Aktualisieren',
            onPressed: controller.loading ? null : controller.refresh,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: SafeArea(child: _logBody(controller)),
    );
  }

  Widget _logBody(LogsController controller) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
        child: Row(
          children: [
            Expanded(
              child: DropdownButton<String>(
                isExpanded: true,
                value: controller.selected,
                hint: const Text('Quelle'),
                items: [
                  for (final source in controller.sources)
                    DropdownMenuItem(
                      value: source.name,
                      enabled: source.available,
                      child: Text(
                        source.available
                            ? source.label
                            : '${source.label} (fehlt)',
                      ),
                    ),
                ],
                onChanged: controller.loading
                    ? null
                    : (name) => name == null ? null : controller.select(name),
              ),
            ),
            const SizedBox(width: 12),
            DropdownButton<int>(
              value: controller.lines,
              items: [
                for (final n in [100, 200, 500, 1000])
                  DropdownMenuItem(value: n, child: Text('$n Zeilen')),
              ],
              onChanged: controller.loading
                  ? null
                  : (n) => n == null ? null : controller.setLines(n),
            ),
          ],
        ),
      ),
      if (controller.loading) const LinearProgressIndicator(),
      if (controller.error != null)
        Padding(
          padding: const EdgeInsets.all(16),
          child: Text(
            '${controller.error}\nLäuft motorpi-logs (Port $logPort) auf dem Pi?',
            style: const TextStyle(color: AppColors.warning),
          ),
        ),
      Expanded(
        child: Container(
          color: AppColors.terminalBackground,
          child: SingleChildScrollView(
            // Starts at the newest line, like `tail`.
            reverse: true,
            padding: const EdgeInsets.all(12),
            child: SelectableText(
              controller.text,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
            ),
          ),
        ),
      ),
    ],
  );
}
