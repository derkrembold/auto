import 'package:motorpi_control/services/known_hosts.dart';

class MemoryKnownHosts implements KnownHosts {
  final pinned = <String, String>{};
  @override
  Future<String?> lookup(String host) async => pinned[host];
  @override
  Future<void> pin(String host, String fingerprint) async =>
      pinned[host] = fingerprint;
  @override
  Future<void> forget(String host) async => pinned.remove(host);
}
