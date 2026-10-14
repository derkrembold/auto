import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:xterm/xterm.dart';
import '../controllers/shell_controller.dart';
import '../theme.dart';

class ShellView extends StatefulWidget {
  const ShellView({super.key});
  @override
  State<ShellView> createState() => _ShellViewState();
}

class _ShellViewState extends State<ShellView> {
  late final ShellController _controller = context.read<ShellController>();
  late final _user = TextEditingController(
    text: _controller.credentials.username,
  );
  late final _password = TextEditingController(
    text: _controller.credentials.password,
  );
  late final _key = TextEditingController(
    text: _controller.credentials.privateKey,
  );

  void _connect() {
    _controller.credentials
      ..username = _user.text
      ..password = _password.text
      ..privateKey = _key.text;
    _controller.connect();
  }

  @override
  void dispose() {
    _user.dispose();
    _password.dispose();
    _key.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<ShellController>();
    final session =
        controller.state == ShellState.connected ||
        controller.state == ShellState.closed;
    return Scaffold(
      appBar: AppBar(
        title: Text('Shell · ${controller.host}'),
        actions: [
          if (controller.state == ShellState.connected)
            IconButton(
              tooltip: 'Trennen',
              onPressed: controller.disconnect,
              icon: const Icon(Icons.link_off),
            ),
          if (controller.state == ShellState.closed)
            IconButton(
              tooltip: 'Neu verbinden',
              onPressed: _connect,
              icon: const Icon(Icons.refresh),
            ),
        ],
      ),
      body: SafeArea(
        child: session ? _terminal(controller) : _loginForm(controller),
      ),
    );
  }

  Widget _loginForm(ShellController controller) => ListView(
    padding: const EdgeInsets.all(20),
    children: [
      const Text(
        'Volle SSH-Shell auf dem Pi – ohne Einschränkungen, auch für Motorbefehle.',
        style: TextStyle(color: AppColors.warning),
      ),
      const SizedBox(height: 16),
      TextField(
        controller: _user,
        autocorrect: false,
        enableSuggestions: false,
        decoration: const InputDecoration(labelText: 'Benutzer'),
      ),
      const SizedBox(height: 12),
      TextField(
        controller: _password,
        obscureText: true,
        decoration: const InputDecoration(labelText: 'Passwort'),
      ),
      const SizedBox(height: 12),
      TextField(
        controller: _key,
        minLines: 2,
        maxLines: 6,
        autocorrect: false,
        enableSuggestions: false,
        style: const TextStyle(fontFamily: 'monospace', fontSize: 11),
        decoration: const InputDecoration(
          labelText: 'Privater Schlüssel (optional, PEM/OpenSSH)',
        ),
      ),
      if (controller.error != null)
        Padding(
          padding: const EdgeInsets.only(top: 12),
          child: Text(
            controller.error!,
            style: const TextStyle(color: AppColors.warning),
          ),
        ),
      const SizedBox(height: 16),
      FilledButton.tonalIcon(
        onPressed: controller.state == ShellState.connecting ? null : _connect,
        icon: const Icon(Icons.terminal),
        label: const Text('Verbinden'),
      ),
      if (controller.state == ShellState.connecting)
        const Padding(
          padding: EdgeInsets.only(top: 12),
          child: LinearProgressIndicator(),
        ),
      const SizedBox(height: 12),
      const Text(
        'Zugangsdaten bleiben nur bis zum Schließen der App im Speicher.',
        style: TextStyle(color: AppColors.muted),
      ),
    ],
  );

  Widget _terminal(ShellController controller) => Column(
    children: [
      Expanded(
        child: TerminalView(
          controller.terminal,
          autofocus: true,
          backgroundOpacity: 1,
          theme: TerminalThemes.defaultTheme,
        ),
      ),
      Material(
        color: Theme.of(context).colorScheme.surfaceContainer,
        child: SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            children: [
              for (final (label, sequence) in const [
                ('Esc', '\x1b'),
                ('Tab', '\t'),
                ('Ctrl-C', '\x03'),
                ('Ctrl-D', '\x04'),
                ('↑', '\x1b[A'),
                ('↓', '\x1b[B'),
                ('←', '\x1b[D'),
                ('→', '\x1b[C'),
              ])
                TextButton(
                  onPressed: controller.state == ShellState.connected
                      ? () => controller.sendRaw(sequence)
                      : null,
                  child: Text(label),
                ),
            ],
          ),
        ),
      ),
    ],
  );
}
