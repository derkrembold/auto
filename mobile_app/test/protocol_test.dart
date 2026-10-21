import 'package:flutter_test/flutter_test.dart';
import 'package:motorpi_control/models/protocol.dart';

void main() {
  test('drive packet matches the Python golden vector', () {
    final session = SessionProtocol();
    expect(session.claim(), [0]);
    final packet = session.command(
      2,
      forward: 800,
      steer: -200,
      held: true,
      speedLimit: 60,
    );
    expect(packet.length, 10);
    expect(
      packet.map((b) => b.toRadixString(16).padLeft(2, '0')).join(),
      '0201000000200338ffbc',
    );
    expect(session.command(3)[1], 2);
  });
  test('hardware problems explain themselves and recovery', () {
    VehicleStatus status(int flags, int error) =>
        VehicleStatus([2, 0, flags, error, ...List.filled(16, 0)]);
    expect(status(5, 0).problem, isNull);
    expect(status(1, 4).problem, contains('Motorsicherung'));
    expect(status(5, 4).problem, contains('Start drücken'));
    expect(status(5, 5).problem, contains('Sicherung prüfen'));
    expect(status(1, 3).problem, contains('neu starten'));
  });
  test('malformed status cannot arm the UI', () {
    expect(() => VehicleStatus([2, 1]), throwsFormatException);
    // Version 1 is the old access-code protocol: refused, not misread.
    expect(() => VehicleStatus(List.filled(20, 1)), throwsFormatException);
  });
}
