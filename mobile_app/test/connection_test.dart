import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:motorpi_control/models/protocol.dart';
import 'package:motorpi_control/services/transport.dart';
import 'package:motorpi_control/services/vehicle_link.dart';

class FakeTransport implements Transport {
  final incoming = StreamController<List<int>>();
  final sent = <List<int>>[];
  bool acceptAuthentication = true, acknowledge = true, closed = false;
  int lastSequence = 0;

  @override
  Stream<List<int>> get input => incoming.stream;

  @override
  void add(List<int> bytes) {
    final packet = bytes.sublist(1);
    sent.add(packet);
    if (packet.length == 17 && acceptAuthentication) {
      emitStatus(authenticated: true);
    }
    if (packet.length == 20 && acknowledge) {
      lastSequence =
          packet[1] | packet[2] << 8 | packet[3] << 16 | packet[4] << 24;
      emitStatus(authenticated: true);
    }
  }

  void frame(String kind, List<int> payload) => scheduleMicrotask(
    () => incoming.add(encodeFrame([kind.codeUnitAt(0), ...payload])),
  );

  void challenge() => frame('C', List.generate(16, (i) => i));

  void emitStatus({required bool authenticated}) => frame('S', [
    1,
    0,
    authenticated ? 6 : 4,
    0,
    0,
    0,
    0,
    0,
    lastSequence & 255,
    lastSequence >> 8 & 255,
    lastSequence >> 16 & 255,
    lastSequence >> 24,
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
  Future<void> close() async {
    closed = true;
  }
}

const key = '000102030405060708090a0b0c0d0e0f';

Future<void> settle() => Future<void>.delayed(const Duration(milliseconds: 30));

VehicleLink linkFor(FakeTransport transport, {Completer<void>? network}) =>
    VehicleLink(
      connector: (host, port) async => transport,
      prepareNetwork: () => network?.future ?? Future<void>.value(),
    );

void main() {
  test('frames survive arbitrary TCP chunking', () {
    final decoder = FrameDecoder();
    final bytes = [
      ...encodeFrame([1, 2, 3]),
      ...encodeFrame([4]),
    ];
    expect(decoder.add(bytes.sublist(0, 2)), isEmpty);
    expect(decoder.add(bytes.sublist(2)), [
      [1, 2, 3],
      [4],
    ]);
  });

  test('authenticates after the challenge and acknowledges commands', () async {
    final transport = FakeTransport();
    final link = linkFor(transport);
    final connecting = link.connect(key);
    await settle();
    expect(transport.sent, isEmpty);
    transport.challenge();
    transport.emitStatus(authenticated: false);
    await connecting.timeout(const Duration(seconds: 2));
    expect(link.connected, isTrue, reason: link.message);
    expect(transport.sent.single.length, 17);
    expect(await link.send(1), isTrue);
    expect(transport.sent.last.length, 20);
    await link.disconnect();
    expect(transport.closed, isTrue);
    link.dispose();
  });

  test('Pi rejection of the access code is shown, not a timeout', () async {
    final transport = FakeTransport()..acceptAuthentication = false;
    final link = linkFor(transport);
    final connecting = link.connect(key);
    transport.challenge();
    await settle();
    transport.frame('E', utf8.encode('Invalid access code'));
    await connecting.timeout(const Duration(seconds: 2));
    expect(link.connected, isFalse);
    expect(link.message, contains('Invalid access code'));
    link.dispose();
  });

  test('missing acknowledgement stops control within 500 ms', () async {
    final transport = FakeTransport();
    final link = linkFor(transport);
    final connecting = link.connect(key);
    transport.challenge();
    await connecting.timeout(const Duration(seconds: 2));
    transport.acknowledge = false;
    final started = DateTime.now();
    expect(await link.send(2, held: true), isFalse);
    expect(DateTime.now().difference(started).inMilliseconds, lessThan(800));
    expect(link.connected, isFalse);
    expect(transport.closed, isTrue);
    link.dispose();
  });

  test('closed socket during a drive is a safety loss', () async {
    final transport = FakeTransport();
    final link = linkFor(transport);
    final connecting = link.connect(key);
    transport.challenge();
    await connecting.timeout(const Duration(seconds: 2));
    await transport.incoming.close();
    await settle();
    expect(link.connected, isFalse);
    expect(link.message, contains('getrennt'));
    link.dispose();
  });

  test('canceled attempt cannot send authentication afterwards', () async {
    final transport = FakeTransport();
    final network = Completer<void>();
    final link = linkFor(transport, network: network);
    final connecting = link.connect(key);
    await settle();
    await link.disconnect();
    network.complete();
    transport.challenge();
    await connecting.timeout(const Duration(seconds: 2));
    expect(link.connected, isFalse);
    expect(transport.sent, isEmpty);
    link.dispose();
  });

  test('no WLAN gives a clear hint', () async {
    final link = VehicleLink(
      connector: (host, port) async => FakeTransport(),
      prepareNetwork: () async => throw StateError('Kein WLAN verbunden.'),
    );
    await link.connect(key);
    expect(link.connected, isFalse);
    expect(link.message, contains('Kein WLAN'));
    link.dispose();
  });
}
