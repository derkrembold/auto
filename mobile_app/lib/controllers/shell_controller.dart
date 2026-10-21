import 'dart:async';
import 'dart:convert';
import 'package:dartssh2/dartssh2.dart';
import 'package:flutter/foundation.dart';
import 'package:xterm/xterm.dart';
import '../app_config.dart';
import '../services/known_hosts.dart';

/// Kept for the app's lifetime (memory only) so reopening the shell does not
/// ask again.
class ShellCredentials {
  String username = 'pi';
  String password = '';
  String privateKey = '';
}

enum ShellState { idle, connecting, confirmHostKey, connected, closed }

/// Full interactive SSH shell on the Pi. Deliberately unrestricted for
/// testing — it can do anything the SSH user can, including starting motors.
/// The Pi's host key is pinned on first use; a different key is refused
/// before any password or private key is used.
class ShellController extends ChangeNotifier {
  ShellController({
    required this.host,
    required this.credentials,
    required this.knownHosts,
  });
  final String host;
  final ShellCredentials credentials;
  final KnownHosts knownHosts;
  final terminal = Terminal(maxLines: 5000);
  ShellState state = ShellState.idle;
  String? error;

  /// Fingerprint awaiting confirmation while [state] is [ShellState.confirmHostKey].
  String? pendingFingerprint;

  /// The presented key differs from the pinned one; offered to [forgetHostKey].
  bool hostKeyChanged = false;
  Completer<bool>? _decision;
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
    hostKeyChanged = false;
    _notify();
    try {
      final key = credentials.privateKey.trim();
      final received = Completer<void>(), checked = Completer<void>();
      final client = _client = SSHClient(
        await SSHSocket.connect(
          host,
          sshPort,
          timeout: const Duration(seconds: 6),
        ),
        username: credentials.username.trim(),
        onVerifyHostKey: (type, fingerprint) async {
          received.complete();
          try {
            return await verifyHostKey(type, fingerprint);
          } finally {
            checked.complete();
          }
        },
        onPasswordRequest: credentials.password.isEmpty
            ? null
            : () => credentials.password,
        identities: key.isEmpty ? null : SSHKeyPair.fromPem(key),
      );
      // The Pi must present its key promptly; the user's confirmation is not timed.
      await Future.any([
        received.future,
        client.authenticated,
      ]).timeout(const Duration(seconds: 10));
      await Future.any([checked.future, client.authenticated]);
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
      // A host key rejection already explains itself.
      error ??= e is SSHAuthError
          ? 'Anmeldung abgelehnt (Benutzer/Passwort/Schlüssel prüfen).'
          : '$e';
      _close();
    }
  }

  /// Accepts the pinned key, asks about an unknown one, refuses a changed one.
  @visibleForTesting
  /// dartssh2 passes the fingerprint already formatted, as UTF-8 bytes of
  /// `SHA256:<base64>`.
  Future<bool> verifyHostKey(String type, Uint8List formatted) async {
    final fingerprint = utf8.decode(formatted);
    final pinned = await knownHosts.lookup(host);
    if (pinned == fingerprint) return true;
    if (pinned != null) {
      hostKeyChanged = true;
      error =
          'Hostschlüssel von $host hat sich geändert – Verbindung abgebrochen, '
          'nichts gesendet. Erwartet $pinned, erhalten $fingerprint. '
          'Das kann ein fremdes Gerät sein, das sich als Pi ausgibt.';
      return false;
    }
    pendingFingerprint = '$type $fingerprint';
    state = ShellState.confirmHostKey;
    final decision = _decision = Completer<bool>();
    _notify();
    final accepted = await decision.future;
    _decision = null;
    pendingFingerprint = null;
    if (!accepted) {
      error = 'Hostschlüssel nicht bestätigt – Verbindung abgebrochen.';
      return false;
    }
    await knownHosts.pin(host, fingerprint);
    state = ShellState.connecting;
    _notify();
    return true;
  }

  void confirmHostKey(bool accepted) => _decision?.complete(accepted);

  /// For a re-imaged Pi: the next connect asks for confirmation again.
  Future<void> forgetHostKey() async {
    await knownHosts.forget(host);
    hostKeyChanged = false;
    error = null;
    _notify();
  }

  /// Keys a phone keyboard lacks (Esc, Tab, Ctrl-C, arrows).
  void sendRaw(String sequence) =>
      _session?.write(Uint8List.fromList(utf8.encode(sequence)));

  void disconnect() => _close();

  void _close() {
    _decision?.complete(false);
    _decision = null;
    pendingFingerprint = null;
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
