import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:motorpi_control/controllers/shell_controller.dart';
import 'memory_known_hosts.dart';

void main() {
  // As dartssh2 hands it over: UTF-8 of the `ssh-keygen -lf` form.
  const fingerprint = 'SHA256:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8';
  final digest = Uint8List.fromList(utf8.encode(fingerprint));

  ShellController shell(MemoryKnownHosts hosts) => ShellController(
    host: 'motorpi.local',
    credentials: ShellCredentials(),
    knownHosts: hosts,
  );

  test('an unknown key waits for confirmation, then is pinned', () async {
    final hosts = MemoryKnownHosts();
    final controller = shell(hosts);
    final verdict = controller.verifyHostKey('ssh-ed25519', digest);
    await pumpEventQueue();
    expect(controller.state, ShellState.confirmHostKey);
    expect(controller.pendingFingerprint, 'ssh-ed25519 $fingerprint');
    controller.confirmHostKey(true);
    expect(await verdict, isTrue);
    expect(hosts.pinned['motorpi.local'], fingerprint);
    expect(controller.pendingFingerprint, isNull);
    controller.dispose();
  });

  test('a declined key is not pinned', () async {
    final hosts = MemoryKnownHosts();
    final controller = shell(hosts);
    final verdict = controller.verifyHostKey('ssh-ed25519', digest);
    await pumpEventQueue();
    controller.confirmHostKey(false);
    expect(await verdict, isFalse);
    expect(hosts.pinned, isEmpty);
    controller.dispose();
  });

  test('the pinned key is accepted without asking', () async {
    final hosts = MemoryKnownHosts()..pinned['motorpi.local'] = fingerprint;
    final controller = shell(hosts);
    expect(await controller.verifyHostKey('ssh-ed25519', digest), isTrue);
    expect(controller.state, isNot(ShellState.confirmHostKey));
    controller.dispose();
  });

  test('a changed key is refused until it is forgotten', () async {
    final hosts = MemoryKnownHosts()
      ..pinned['motorpi.local'] = 'SHA256:somethingElse';
    final controller = shell(hosts);
    expect(await controller.verifyHostKey('ssh-ed25519', digest), isFalse);
    expect(controller.hostKeyChanged, isTrue);
    expect(controller.error, contains('geändert'));
    expect(hosts.pinned['motorpi.local'], 'SHA256:somethingElse');
    await controller.forgetHostKey();
    expect(hosts.pinned, isEmpty);
    expect(controller.hostKeyChanged, isFalse);
    controller.dispose();
  });

  test('leaving the shell during confirmation rejects the key', () async {
    final hosts = MemoryKnownHosts();
    final controller = shell(hosts);
    final verdict = controller.verifyHostKey('ssh-ed25519', digest);
    await pumpEventQueue();
    controller.dispose();
    expect(await verdict, isFalse);
    expect(hosts.pinned, isEmpty);
  });
}
