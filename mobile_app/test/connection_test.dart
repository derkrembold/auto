import 'dart:async';
import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_reactive_ble/flutter_reactive_ble.dart';
import 'package:motorpi_control/protocol.dart';
import 'package:motorpi_control/vehicle_link.dart';

class FakeBle extends Fake implements FlutterReactiveBle {
  final discovery = Completer<void>();
  final updates = StreamController<ConnectionStateUpdate>();
  final notifications = StreamController<List<int>>();
  final calls = <String>[];
  bool acceptAuthentication = true;
  int writes = 0;

  @override
  Stream<ConnectionStateUpdate> connectToDevice({
    required String id,
    Map<Uuid, List<Uuid>>? servicesWithCharacteristicsToDiscover,
    Duration? connectionTimeout,
  }) {
    scheduleMicrotask(
      () => updates.add(
        ConnectionStateUpdate(
          deviceId: id,
          connectionState: DeviceConnectionState.connected,
          failure: null,
        ),
      ),
    );
    return updates.stream;
  }

  @override
  Future<void> discoverAllServices(String deviceId) {
    calls.add('discover');
    return discovery.future;
  }

  @override
  Future<List<int>> readCharacteristic(
    QualifiedCharacteristic characteristic,
  ) async {
    calls.add('challenge');
    return List.generate(16, (i) => i);
  }

  @override
  Stream<List<int>> subscribeToCharacteristic(
    QualifiedCharacteristic characteristic,
  ) {
    calls.add('subscribe');
    return notifications.stream;
  }

  void emitStatus(bool authenticated) => notifications.add([
    1,
    0,
    authenticated ? 6 : 4,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    176,
    4,
    88,
    2,
    0,
    0,
    0,
    0,
  ]);
  @override
  Future<void> writeCharacteristicWithoutResponse(
    QualifiedCharacteristic characteristic, {
    required List<int> value,
  }) async {
    calls.add('authenticate');
    writes++;
    if (acceptAuthentication) emitStatus(true);
  }

  void close() {
    unawaited(updates.close());
    unawaited(notifications.close());
  }
}

final device = DiscoveredDevice(
  id: 'test-pi',
  name: 'MotorPi',
  serviceData: {},
  manufacturerData: Uint8List(0),
  rssi: -40,
  serviceUuids: [Uuid.parse(serviceUuid)],
);
const key = '000102030405060708090a0b0c0d0e0f';

Future<void> settle() => Future<void>.delayed(const Duration(milliseconds: 30));

void main() {
  test('slow Android discovery can take longer than three seconds', () async {
    final ble = FakeBle();
    final link = VehicleLink(ble: ble);
    final connecting = link.connect(device, key);
    await Future<void>.delayed(const Duration(seconds: 4));
    expect(link.connecting, isTrue);
    expect(ble.calls, ['discover']);
    ble.discovery.complete();
    await settle();
    expect(ble.calls, [
      'discover',
      'challenge',
      'subscribe',
    ], reason: link.message);
    expect(ble.writes, 0);
    ble.emitStatus(false);
    await connecting.timeout(const Duration(seconds: 2));
    expect(link.connected, isTrue, reason: link.message);
    expect(ble.writes, 1);
    await link.disconnect();
    link.dispose();
    ble.close();
  });

  test(
    'authentication waits for Pi confirmation after write completes',
    () async {
      final ble = FakeBle()..acceptAuthentication = false;
      ble.discovery.complete();
      final link = VehicleLink(ble: ble);
      final connecting = link.connect(device, key);
      await settle();
      ble.emitStatus(false);
      await settle();
      expect(ble.writes, 1, reason: link.message);
      expect(link.connected, isFalse);
      ble.emitStatus(true);
      await connecting.timeout(const Duration(seconds: 2));
      expect(link.connected, isTrue, reason: link.message);
      await link.disconnect();
      link.dispose();
      ble.close();
    },
  );

  test(
    'timeout identifies discovery rather than blaming the access code',
    () async {
      final ble = FakeBle();
      final link = VehicleLink(ble: ble);
      await link.connect(device, key).timeout(const Duration(seconds: 18));
      expect(link.connected, isFalse);
      expect(
        link.message,
        contains('Zeitüberschreitung: Bluetooth-Dienste suchen'),
      );
      expect(link.message, isNot(contains('Zugangscode')));
      link.dispose();
      ble.close();
    },
  );

  test('canceled discovery cannot send authentication afterwards', () async {
    final ble = FakeBle();
    final link = VehicleLink(ble: ble);
    final connecting = link.connect(device, key);
    await settle();
    await link.disconnect();
    ble.discovery.complete();
    await connecting.timeout(const Duration(seconds: 2));
    expect(link.connected, isFalse);
    expect(ble.calls, ['discover']);
    expect(ble.writes, 0);
    link.dispose();
    ble.close();
  });
}
