import 'dart:async';
import 'package:flutter_test/flutter_test.dart';
import 'package:motorpi_control/controllers/drive_controller.dart';
import 'package:motorpi_control/models/gamepad_event.dart';
import 'package:motorpi_control/models/protocol.dart';
import 'package:motorpi_control/services/vehicle_link.dart';

/// Connected, ready link that acknowledges everything like the Pi.
class ReadyLink extends VehicleLink {
  ReadyLink() {
    connected = true;
    status = _status(0);
    lastStatus = DateTime.now();
  }
  final commands = <int>[];
  static VehicleStatus _status(int state) => VehicleStatus(
    List<int>.filled(20, 0)
      ..[0] = 1
      ..[1] = state
      ..[2] = 6,
  );
  @override
  Future<bool> send(
    int operation, {
    int forward = 0,
    int steer = 0,
    bool held = false,
    int speedLimit = 100,
  }) async {
    commands.add(operation);
    status = _status(operation == 3 ? 0 : 1);
    lastStatus = DateTime.now();
    notifyListeners();
    return true;
  }
}

/// Like [ReadyLink], but DRIVE packets stay in flight (busy) until released.
class SlowDriveLink extends ReadyLink {
  Completer<void>? inFlight;
  bool disconnected = false;
  @override
  Future<bool> send(
    int operation, {
    int forward = 0,
    int steer = 0,
    bool held = false,
    int speedLimit = 100,
  }) async {
    if (busy) return false;
    if (operation != 2) return super.send(operation);
    busy = true;
    final pending = inFlight = Completer<void>();
    await pending.future;
    busy = false;
    return super.send(operation);
  }

  @override
  Future<void> disconnect() async {
    disconnected = true;
    connected = false;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('a covered drive screen stops and ignores gamepad start', () async {
    final link = ReadyLink();
    final pad = StreamController<GamepadEvent>();
    final drive = DriveController(link: link, gamepad: pad.stream);
    await drive.setUseGamepad(true);
    await drive.start();
    expect(drive.armed, isTrue);
    final covered = Completer<void>();
    final suspended = drive.suspendWhile(() => covered.future);
    await pumpEventQueue();
    expect(drive.armed, isFalse);
    expect(link.commands.last, 3);
    pad.add(const GamepadEvent(name: 'Pad', start: true));
    await pumpEventQueue();
    expect(drive.armed, isFalse);
    expect(link.commands.where((c) => c == 1).length, 1);
    covered.complete();
    await suspended;
    pad.add(const GamepadEvent(name: 'Pad', start: true));
    await pumpEventQueue();
    expect(drive.armed, isTrue);
    drive.dispose();
    await pad.close();
    link.dispose();
  });

  test('leaving the drive screen while armed sends a stop', () async {
    final link = ReadyLink();
    final drive = DriveController(link: link, gamepad: const Stream.empty());
    await drive.start();
    expect(drive.armed, isTrue);
    drive.dispose();
    await pumpEventQueue();
    expect(link.commands, [1, 3]);
    link.dispose();
  });

  test('leaving with a drive packet in flight stops after it', () async {
    final link = SlowDriveLink();
    final drive = DriveController(link: link, gamepad: const Stream.empty());
    await drive.start();
    unawaited(link.send(2));
    expect(link.busy, isTrue);
    drive.dispose();
    await pumpEventQueue();
    link.inFlight!.complete();
    await Future<void>.delayed(const Duration(milliseconds: 50));
    expect(link.commands, [1, 2, 3]);
    expect(link.disconnected, isFalse);
    link.dispose();
  });

  test('leaving with a stalled drive packet closes the link', () async {
    final link = SlowDriveLink();
    final drive = DriveController(link: link, gamepad: const Stream.empty());
    await drive.start();
    unawaited(link.send(2));
    drive.dispose();
    await Future<void>.delayed(const Duration(milliseconds: 700));
    expect(link.commands, [1]);
    expect(link.disconnected, isTrue);
    link.dispose();
  });

  test('gamepad disconnect stops an armed drive', () async {
    final link = ReadyLink();
    final pad = StreamController<GamepadEvent>();
    final drive = DriveController(link: link, gamepad: pad.stream);
    await drive.setUseGamepad(true);
    await drive.start();
    pad.add(const GamepadEvent(name: 'Pad', connected: false));
    await pumpEventQueue();
    expect(drive.armed, isFalse);
    expect(link.commands.last, 3);
    drive.dispose();
    await pad.close();
    link.dispose();
  });
}
