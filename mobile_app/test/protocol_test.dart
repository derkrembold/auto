import 'package:flutter_test/flutter_test.dart';
import 'package:motorpi_control/models/protocol.dart';

void main() {
  test(
    'Android drive packet matches the Python golden vector at minimum MTU',
    () {
      final session = SessionProtocol(
        List.generate(16, (i) => i),
        List.generate(16, (i) => i + 16),
      );
      final packet = session.command(
        2,
        forward: 800,
        steer: -200,
        held: true,
        speedLimit: 60,
      );
      expect(packet.length, 20);
      expect(
        packet.map((b) => b.toRadixString(16).padLeft(2, '0')).join(),
        '0201000000200338ffbcf44a504bf24fee57903f',
      );
      expect(session.command(3)[1], 2);
    },
  );
  test('access code validation never substitutes a default credential', () {
    expect(() => parseKey('raspberry'), throwsFormatException);
    expect(
      parseKey('000102030405060708090A0B0C0D0E0F'),
      List.generate(16, (i) => i),
    );
  });
  test('hardware problems explain themselves and recovery', () {
    VehicleStatus status(int flags, int error) =>
        VehicleStatus([1, 0, flags, error, ...List.filled(16, 0)]);
    expect(status(5, 0).problem, isNull);
    expect(status(1, 4).problem, contains('Motorsicherung'));
    expect(status(5, 4).problem, contains('Start drücken'));
    expect(status(5, 5).problem, contains('Sicherung prüfen'));
    expect(status(1, 3).problem, contains('neu starten'));
  });
  test('malformed status cannot arm the UI', () {
    expect(() => VehicleStatus([1, 1]), throwsFormatException);
    expect(() => VehicleStatus(List.filled(20, 2)), throwsFormatException);
  });
  test('short access code derives the same key as Python', () {
    expect(parseKey('abcd-2345'), parseKey('ABCD2345'));
    expect(
      parseKey(
        'ABCD2345',
      ).map((b) => b.toRadixString(16).padLeft(2, '0')).join(),
      'd82b612e9353915b09090d57cf69bf16',
    );
    expect(() => parseKey('ABCD0123'), throwsFormatException);
  });
}
