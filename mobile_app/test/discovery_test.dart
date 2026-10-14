import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:motorpi_control/controllers/discovery_controller.dart';
import 'package:motorpi_control/models/protocol.dart';
import 'package:motorpi_control/routes.dart';
import 'package:motorpi_control/services/pi_discovery.dart';
import 'package:motorpi_control/services/transport.dart';
import 'package:motorpi_control/services/vehicle_link.dart';

/// Replies like wifi_server.py does on accept: challenge + status, or a rejection.
class ProbeTransport implements Transport {
  ProbeTransport({bool live = false, String? reject, bool silent = false}) {
    scheduleMicrotask(() {
      if (silent) return;
      if (reject != null) {
        incoming.add(encodeFrame([0x45, ...utf8.encode(reject)]));
        return;
      }
      final status = List<int>.filled(20, 0)
        ..[0] = 1
        ..[2] = live ? 5 : 4;
      incoming.add([
        ...encodeFrame([0x43, ...List.filled(16, 7)]),
        ...encodeFrame([0x53, ...status]),
      ]);
    });
  }
  final incoming = StreamController<List<int>>();
  bool closed = false;
  @override
  Stream<List<int>> get input => incoming.stream;
  @override
  void add(List<int> bytes) {}
  @override
  Future<void> close() async => closed = true;
}

/// Every name resolves to the access point, as dnsmasq does on the Pi.
Future<List<InternetAddress>> lookup(String host) async => [
  InternetAddress('10.42.0.1'),
];

void main() {
  test('probe reads mode, occupancy and closes the connection', () async {
    final transports = <String, ProbeTransport>{
      'a': ProbeTransport(live: true),
      'b': ProbeTransport(reject: 'Another phone owns the control session'),
      'c': ProbeTransport(silent: true),
    };
    final discovery = PiDiscovery(
      connector: (host, port) async => transports[host]!,
      lookup: lookup,
    );
    final live = await discovery.probe('a');
    expect((live.reachable, live.live, live.occupied), (true, true, false));
    final busy = await discovery.probe('b');
    expect(
      (busy.reachable, busy.occupied, busy.selectable),
      (true, true, false),
    );
    final silent = await discovery.probe(
      'c',
      timeout: const Duration(milliseconds: 50),
    );
    expect(silent.reachable, isFalse);
    expect(transports.values.every((t) => t.closed), isTrue);
  });

  test('scan collapses two names for the same Pi', () async {
    final discovery = PiDiscovery(
      connector: (host, port) async => host == 'nowhere'
          ? throw const SocketException('refused')
          : ProbeTransport(),
      lookup: (host) async => [
        InternetAddress(host == 'nowhere' ? '10.0.0.9' : '10.42.0.1'),
      ],
    );
    final results = await discovery.scan([
      defaultHost,
      'motorpi.local',
      'nowhere',
    ]);
    expect(results.map((pi) => (pi.host, pi.reachable)), [
      (defaultHost, true),
      ('nowhere', false),
    ]);
  });

  test('auto-select happens once and needs exactly one free Pi', () async {
    final link = VehicleLink(connector: (_, _) async => ProbeTransport());
    final controller = DiscoveryController(
      discovery: PiDiscovery(
        connector: (host, port) async => ProbeTransport(),
        lookup: lookup,
      ),
      link: link,
      autoSelect: true,
      prepareNetwork: () async {},
    );
    await controller.scan();
    expect(controller.results.length, 1);
    expect(controller.takeAutoSelection()?.host, defaultHost);
    expect(controller.takeAutoSelection(), isNull);
    link.dispose();
  });

  test(
    'without a debug code selection leads to the access-code screen',
    () async {
      final link = VehicleLink(connector: (_, _) async => ProbeTransport());
      final controller = DiscoveryController(
        discovery: PiDiscovery(lookup: lookup),
        link: link,
        prepareNetwork: () async {},
      );
      final route = await controller.select(
        (await PiDiscovery(
          connector: (_, _) async => ProbeTransport(),
          lookup: lookup,
        ).probe(defaultHost)),
      );
      expect(route, Routes.accessCode);
      expect(link.connecting, isFalse);
      link.dispose();
    },
  );

  test('a rejected debug code falls back to the access-code screen', () async {
    final link = VehicleLink(
      connector: (_, _) async => ProbeTransport(reject: 'Invalid access code'),
      prepareNetwork: () async {},
    );
    final controller = DiscoveryController(
      discovery: PiDiscovery(lookup: lookup),
      link: link,
      accessCode: 'ABCD2345',
      prepareNetwork: () async {},
    );
    final pi = await PiDiscovery(
      connector: (_, _) async => ProbeTransport(),
      lookup: lookup,
    ).probe(defaultHost);
    expect(await controller.select(pi), Routes.accessCode);
    expect(link.message, contains('Invalid access code'));
    link.dispose();
  });
}
