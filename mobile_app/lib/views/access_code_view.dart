import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../controllers/access_code_controller.dart';
import '../routes.dart';
import '../theme.dart';
import 'tools_menu.dart';

class AccessCodeView extends StatefulWidget {
  const AccessCodeView({super.key});
  @override
  State<AccessCodeView> createState() => _AccessCodeViewState();
}

class _AccessCodeViewState extends State<AccessCodeView> {
  final _code = TextEditingController();

  Future<void> _submit() async {
    final ok = await context.read<AccessCodeController>().submit(_code.text);
    if (ok && mounted) {
      await Navigator.of(
        context,
      ).pushNamedAndRemoveUntil(Routes.control, (_) => false);
    }
  }

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<AccessCodeController>();
    return Scaffold(
      appBar: AppBar(
        title: const Text('Zugangscode'),
        actions: [ToolsMenu(host: controller.host)],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 640),
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      'Pi unter ${controller.host}',
                      style: Theme.of(context).textTheme.headlineSmall,
                    ),
                    const SizedBox(height: 8),
                    Text(controller.message),
                    const SizedBox(height: 20),
                    TextField(
                      controller: _code,
                      autofocus: true,
                      autocorrect: false,
                      enableSuggestions: false,
                      textCapitalization: TextCapitalization.characters,
                      decoration: const InputDecoration(
                        labelText: 'Persönlicher Zugangscode',
                        hintText: '8 Zeichen aus der Pi-Einrichtung',
                      ),
                      onSubmitted: (_) => _submit(),
                    ),
                    const SizedBox(height: 12),
                    FilledButton.tonalIcon(
                      onPressed: controller.connecting ? null : _submit,
                      icon: const Icon(Icons.wifi),
                      label: const Text('Verbinden'),
                    ),
                    const SizedBox(height: 12),
                    if (controller.connecting) const LinearProgressIndicator(),
                    const SizedBox(height: 20),
                    const Text(
                      'Der Code bleibt nur bis zum Schließen der App im Speicher.',
                      style: TextStyle(color: AppColors.muted),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
