import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../controllers/discovery_controller.dart';
import '../models/discovered_pi.dart';
import '../routes.dart';
import '../theme.dart';
import 'tools_menu.dart';

class DiscoveryView extends StatefulWidget {
  const DiscoveryView({super.key});
  @override
  State<DiscoveryView> createState() => _DiscoveryViewState();
}

class _DiscoveryViewState extends State<DiscoveryView> {
  final _host = TextEditingController();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _scan());
  }

  Future<void> _scan() async {
    final controller = context.read<DiscoveryController>();
    await controller.scan();
    final only = controller.takeAutoSelection();
    if (only != null && mounted) await _select(only);
  }

  Future<void> _select(DiscoveredPi pi) async {
    final connected = await context.read<DiscoveryController>().select(pi);
    if (!mounted || !connected) return;
    await Navigator.of(
      context,
    ).pushNamedAndRemoveUntil(Routes.control, (_) => false);
  }

  void _addHost() {
    context.read<DiscoveryController>().addHost(_host.text);
    _host.clear();
    _scan();
  }

  @override
  void dispose() {
    _host.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<DiscoveryController>();
    final busy = controller.scanning || controller.selecting;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Pi suchen'),
        actions: [ToolsMenu(host: controller.bestHost)],
      ),
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _scan,
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Text(
                controller.link.message,
                style: Theme.of(context).textTheme.titleMedium,
              ),
              if (controller.networkError != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    controller.networkError!,
                    style: const TextStyle(color: AppColors.warning),
                  ),
                ),
              const SizedBox(height: 12),
              if (busy) const LinearProgressIndicator(),
              for (final pi in controller.results)
                Card(
                  child: ListTile(
                    enabled: pi.selectable && !busy,
                    leading: Icon(
                      pi.reachable ? Icons.router : Icons.portable_wifi_off,
                    ),
                    title: Text(pi.host),
                    subtitle: Text(
                      pi.reachable
                          ? '${pi.modeLabel} · ${pi.latency!.inMilliseconds} ms'
                          : '${pi.modeLabel}: ${pi.error}',
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    trailing: pi.selectable
                        ? const Icon(Icons.chevron_right)
                        : null,
                    onTap: () => _select(pi),
                  ),
                ),
              if (!busy &&
                  controller.results.isNotEmpty &&
                  controller.results.every((pi) => !pi.reachable))
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 8),
                  child: Text(
                    'Kein Pi gefunden. Nach unten ziehen zum erneuten Suchen.',
                  ),
                ),
              const SizedBox(height: 16),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _host,
                      autocorrect: false,
                      enableSuggestions: false,
                      keyboardType: TextInputType.url,
                      decoration: const InputDecoration(
                        labelText: 'Weitere Adresse',
                        hintText: 'z. B. 192.168.1.42',
                      ),
                      onSubmitted: (_) => _addHost(),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton.filledTonal(
                    tooltip: 'Hinzufügen und suchen',
                    onPressed: busy ? null : _addHost,
                    icon: const Icon(Icons.add),
                  ),
                ],
              ),
              const SizedBox(height: 20),
              const Text(
                'Die Steuerung läuft über das WLAN „MotorPi“. Fragt Android, ob die Verbindung ohne Internet bleiben soll: Ja.',
                style: TextStyle(color: AppColors.muted),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
