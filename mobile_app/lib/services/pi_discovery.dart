import 'dart:async';
import 'dart:convert';
import 'dart:io';
import '../models/discovered_pi.dart';
import '../models/protocol.dart';
import 'transport.dart';

typedef Lookup = Future<List<InternetAddress>> Function(String host);

/// Finds the Pi by opening a short control connection: the server answers
/// immediately with a challenge plus status, or with a rejection when another
/// phone owns the session. An unauthenticated connection has no side effects.
class PiDiscovery {
  PiDiscovery({Connector? connector, Lookup? lookup})
    : _connector = connector ?? SocketTransport.connect,
      _lookup = lookup ?? InternetAddress.lookup;
  final Connector _connector;
  final Lookup _lookup;

  Future<DiscoveredPi> probe(
    String host, {
    int port = defaultPort,
    Duration timeout = const Duration(seconds: 2),
  }) async {
    final watch = Stopwatch()..start();
    Transport? transport;
    String? address;
    try {
      final addresses = await _lookup(host).timeout(timeout);
      address = addresses.isEmpty ? null : addresses.first.address;
      transport = await _connector(host, port).timeout(timeout);
      final decoder = FrameDecoder();
      VehicleStatus? status;
      String? rejection;
      await for (final bytes in transport.input.timeout(timeout)) {
        for (final frame in decoder.add(bytes)) {
          if (frame.isEmpty) continue;
          if (frame[0] == 0x53) status = VehicleStatus(frame.sublist(1));
          if (frame[0] == 0x45) {
            rejection = utf8.decode(frame.sublist(1), allowMalformed: true);
          }
        }
        if (status != null || rejection != null) break;
      }
      if (status == null && rejection == null) {
        throw StateError('Keine Antwort vom Pi');
      }
      return DiscoveredPi(
        host: host,
        port: port,
        address: address,
        live: status?.live ?? false,
        occupied: rejection != null,
        latency: watch.elapsed,
      );
    } catch (error) {
      return DiscoveredPi(
        host: host,
        port: port,
        address: address,
        error: error is TimeoutException ? 'Zeitüberschreitung' : '$error',
      );
    } finally {
      await transport?.close();
    }
  }

  /// Probes all hosts in parallel; reachable first, duplicates by IP removed.
  Future<List<DiscoveredPi>> scan(Iterable<String> hosts) async {
    final results = await Future.wait({...hosts}.map(probe));
    final seen = <String>{};
    final unique = <DiscoveredPi>[];
    for (final pi in [
      ...results.where((pi) => pi.reachable),
      ...results.where((pi) => !pi.reachable),
    ]) {
      if (pi.reachable && pi.address != null && !seen.add(pi.address!)) {
        continue;
      }
      unique.add(pi);
    }
    return unique;
  }
}
