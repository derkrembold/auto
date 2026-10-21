import 'dart:async';
import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:motorpi_control/controllers/shell_controller.dart';
import 'package:motorpi_control/main.dart';
import 'package:motorpi_control/models/protocol.dart';
import 'package:motorpi_control/services/known_hosts.dart';
import 'package:motorpi_control/services/pi_discovery.dart';
import 'package:motorpi_control/services/transport.dart';
import 'package:motorpi_control/services/vehicle_link.dart';
import 'package:provider/provider.dart';
import 'memory_known_hosts.dart';

/// A Pi that greets like wifi_server.py and accepts any login.
class PiTransport implements Transport {
  PiTransport() {
    scheduleMicrotask(() {
      incoming.add(encodeFrame([0x43, ...List.filled(16, 7)]));
      _status(authenticated: false);
    });
  }
  final incoming = StreamController<List<int>>();
  void _status({required bool authenticated}) => incoming.add(
    encodeFrame([
      0x53,
      ...List<int>.filled(20, 0)
        ..[0] = 1
        ..[2] = authenticated ? 6 : 4,
    ]),
  );
  @override
  Stream<List<int>> get input => incoming.stream;
  @override
  void add(List<int> bytes) {
    if (bytes.length == 18) _status(authenticated: true);
  }

  @override
  Future<void> close() async {}
}

void main() {
  testWidgets('launch finds the Pi, asks for the code, drives, and returns '
      'to discovery when the connection drops', (tester) async {
    final messenger = tester.binding.defaultBinaryMessenger;
    for (final name in ['motorpi/platform', 'motorpi/gamepad']) {
      messenger.setMockMethodCallHandler(
        MethodChannel(name),
        (call) async => call.method == 'bindWifi' ? true : null,
      );
      addTearDown(
        () => messenger.setMockMethodCallHandler(MethodChannel(name), null),
      );
    }
    final transports = <PiTransport>[];
    final link = VehicleLink(
      connector: (_, _) async => (transports..add(PiTransport())).last,
      prepareNetwork: () async {},
    );
    final discovery = PiDiscovery(
      connector: (_, _) async => PiTransport(),
      lookup: (_) async => [InternetAddress('10.42.0.1')],
    );
    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider.value(value: link),
          Provider.value(value: discovery),
          Provider(create: (_) => ShellCredentials()),
          Provider<KnownHosts>(create: (_) => MemoryKnownHosts()),
        ],
        child: const MotorPiApp(),
      ),
    );
    Future<void> settle() async {
      for (var i = 0; i < 10; i++) {
        await tester.runAsync(() => Future<void>.delayed(Duration.zero));
        await tester.pump(const Duration(milliseconds: 100));
      }
    }

    await settle();
    // Exactly one free Pi: discovery continues to the code on its own.
    expect(find.text('Pi unter $defaultHost'), findsOneWidget);
    await tester.enterText(find.byType(EditableText), 'ABCD2345');
    await tester.tap(find.text('Verbinden'));
    await settle();
    expect(find.text('START'), findsOneWidget);
    expect(link.host, defaultHost);
    await transports.last.incoming.close();
    await settle();
    expect(find.text('Pi suchen'), findsOneWidget);
    expect(find.textContaining('getrennt'), findsOneWidget);
    await tester.pumpWidget(const SizedBox());
    link.dispose();
  });
}
