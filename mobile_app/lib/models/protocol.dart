import 'dart:typed_data';

const defaultHost = '10.42.0.1';
const defaultPort = 8765;

/// Protocol version 2: no access code, being on the MotorPi WLAN is enough.
const protocolVersion = 2;

/// One length byte, then the payload. Pi frames start with a kind byte:
/// `S` status, `E` UTF-8 rejection reason.
List<int> encodeFrame(List<int> payload) {
  if (payload.length > 255) throw RangeError('Frame zu lang');
  return [payload.length, ...payload];
}

class FrameDecoder {
  final _buffer = <int>[];

  /// Returns every complete payload; incomplete bytes stay buffered.
  List<List<int>> add(List<int> bytes) {
    _buffer.addAll(bytes);
    final frames = <List<int>>[];
    while (_buffer.isNotEmpty && _buffer.length > _buffer[0]) {
      final size = _buffer[0];
      frames.add(_buffer.sublist(1, 1 + size));
      _buffer.removeRange(0, 1 + size);
    }
    if (_buffer.length > 512) {
      throw const FormatException('Ungültiger Datenstrom');
    }
    return frames;
  }
}

/// Per connection: claims control once, then numbers every command.
class SessionProtocol {
  int sequence = 0;

  /// Takes control; the Pi admits only one phone at a time.
  List<int> claim() => const [0];

  List<int> command(
    int operation, {
    int forward = 0,
    int steer = 0,
    bool held = false,
    int speedLimit = 100,
  }) {
    if (sequence >= 0xfffffffe) throw StateError('Bitte neu verbinden');
    if (forward.abs() > 1000 || steer.abs() > 1000) {
      throw RangeError('Steuerwert');
    }
    final body = ByteData(10)
      ..setUint8(0, operation)
      ..setUint32(1, ++sequence, Endian.little)
      ..setInt16(5, forward, Endian.little)
      ..setInt16(7, steer, Endian.little)
      ..setUint8(
        9,
        operation == 2 ? ((held ? 128 : 0) | speedLimit.clamp(0, 100)) : 0,
      );
    return body.buffer.asUint8List();
  }
}

class VehicleStatus {
  VehicleStatus(List<int> bytes) {
    if (bytes.length != 20 || bytes[0] != protocolVersion) {
      throw const FormatException(
        'Unbekanntes Pi-Protokoll – App und Pi-Dienst auf den gleichen Stand bringen.',
      );
    }
    final data = ByteData.sublistView(Uint8List.fromList(bytes));
    state = data.getUint8(1);
    live = data.getUint8(2) & 1 != 0;
    claimed = data.getUint8(2) & 2 != 0;
    ready = data.getUint8(2) & 4 != 0;
    error = data.getUint8(3);
    left = data.getInt16(4, Endian.little);
    right = data.getInt16(6, Endian.little);
    ack = data.getUint32(8, Endian.little);
    maxRpm = data.getUint16(12, Endian.little);
  }
  late final int state, error, left, right, ack, maxRpm;
  late final bool live, claimed, ready;
  bool get armed => state == 1;
  String get label => switch (state) {
    1 => 'FAHRBEREIT',
    2 => 'WIRD ANGEHALTEN',
    3 => 'STÖRUNG',
    _ => 'GESTOPPT',
  };

  /// What the driver should do; null while everything is fine.
  String? get problem => switch (error) {
    0 => ready ? null : 'Warte auf Motoren …',
    1 => 'Verbindung oder Eingabe ausgeblieben. Erneut Start drücken.',
    4 =>
      ready
          ? 'Motoren wieder erreichbar. Start drücken.'
          : 'Motoren nicht erreichbar. Motorsicherung und Stromversorgung prüfen – '
                'Start wird automatisch frei, sobald sie antworten.',
    5 =>
      ready
          ? 'Motor drehte nicht (Sicherung aus oder blockiert). '
                'Sicherung prüfen, dann erneut Start.'
          : 'Motor drehte nicht. Motorsteuerung wird zurückgesetzt …',
    _ =>
      'Störung am Pi (Hardware/Überstrom). Vor Ort prüfen und Dienst neu starten.',
  };
}
