import 'dart:async';
import 'dart:convert';
import 'package:dartssh2/dartssh2.dart';
import 'package:flutter/foundation.dart';
import 'package:xterm/xterm.dart';
import '../app_config.dart';

/// Kept for the app's lifetime (memory only) so reopening the shell does not
/// ask again.
class ShellCredentials {
  String username = 'pi';
  String password = '';
  String privateKey = '';
}

enum ShellState { idle, connecting, connected, closed }

/// Full interactive SSH shell on the Pi. Deliberately unrestricted for
/// testing — it can do anything the SSH user can, including starting motors.
class ShellController extends ChangeNotifier {
  ShellController({required this.host, required this.credentials});
  final String host;
  final ShellCredentials credentials;
  final terminal = Terminal(maxLines: 5000);
  ShellState state = ShellState.idle;
  String? error;
  SSHClient? _client;
  SSHSession? _session;
  final _subscriptions = <StreamSubscription<String>>[];
  bool _disposed = false;

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  Future<void> connect() async {
    if (state == ShellState.connecting || state == ShellState.connected) return;
    state = ShellState.connecting;
    error = null;
    _notify();
    try {
      final key = credentials.privateKey.trim();
      final client = _client = SSHClient(
        await SSHSocket.connect(
          host,
          sshPort,
          timeout: const Duration(seconds: 6),
        ),
        username: credentials.username.trim(),
        onPasswordRequest: credentials.password.isEmpty
            ? null
            : () => credentials.password,
        identities: key.isEmpty ? null : SSHKeyPair.fromPem(key),
      );
      await client.authenticated.timeout(const Duration(seconds: 10));
      final session = _session = await client.shell(
        pty: SSHPtyConfig(
          width: terminal.viewWidth,
          height: terminal.viewHeight,
        ),
      );
      terminal.onOutput = (data) => session.write(utf8.encode(data));
      terminal.onResize = (w, h, pw, ph) =>
          session.resizeTerminal(w, h, pw, ph);
      for (final stream in [session.stdout, session.stderr]) {
        _subscriptions.add(
          const Utf8Decoder(
            allowMalformed: true,
          ).bind(stream).listen(terminal.write),
        );
      }
      state = ShellState.connected;
      _notify();
      unawaited(
        session.done.whenComplete(() {
          terminal.write('\r\n[Sitzung beendet]\r\n');
          _close();
        }),
      );
    } catch (e) {
      error = e is SSHAuthError
          ? 'Anmeldung abgelehnt (Benutzer/Passwort/Schlüssel prüfen).'
          : '$e';
      _close();
    }
  }

  /// Keys a phone keyboard lacks (Esc, Tab, Ctrl-C, arrows).
  void sendRaw(String sequence) =>
      _session?.write(Uint8List.fromList(utf8.encode(sequence)));

  void disconnect() => _close();

  void _close() {
    for (final subscription in _subscriptions) {
      unawaited(subscription.cancel());
    }
    _subscriptions.clear();
    _session?.close();
    _client?.close();
    _session = null;
    _client = null;
    terminal.onOutput = null;
    terminal.onResize = null;
    // A failed attempt returns to the login form; an ended session offers reconnect.
    state = error != null || state == ShellState.idle
        ? ShellState.idle
        : ShellState.closed;
    _notify();
  }

  @override
  void dispose() {
    _disposed = true;
    _close();
    super.dispose();
  }
}
