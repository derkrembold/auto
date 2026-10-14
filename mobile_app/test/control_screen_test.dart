import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:motorpi_control/controllers/drive_controller.dart';
import 'package:motorpi_control/models/protocol.dart';
import 'package:motorpi_control/services/vehicle_link.dart';
import 'package:motorpi_control/views/control/control_view.dart';
import 'package:motorpi_control/views/control/joystick.dart';
import 'package:provider/provider.dart';

class FakeLink extends VehicleLink {
  FakeLink() {
    connected = true;
    status = VehicleStatus([
      1,
      0,
      6,
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
    lastStatus = DateTime.now();
  }
  final commands = <int>[];
  final driveValues = <(int, bool)>[];
  @override
  Future<bool> send(
    int operation, {
    int forward = 0,
    int steer = 0,
    bool held = false,
    int speedLimit = 100,
  }) async {
    commands.add(operation);
    if (operation == 2) driveValues.add((forward, held));
    final bytes = List<int>.filled(20, 0);
    bytes[0] = 1;
    bytes[1] = operation == 3 ? 0 : 1;
    bytes[2] = 6;
    status = VehicleStatus(bytes);
    lastStatus = DateTime.now();
    notifyListeners();
    return true;
  }
}

Widget controlScreen(VehicleLink link) =>
    ChangeNotifierProvider<VehicleLink>.value(
      value: link,
      child: MaterialApp(
        home: ChangeNotifierProvider(
          create: (_) => DriveController(link: link),
          child: const ControlView(),
        ),
      ),
    );

void main() {
  for (final size in [const Size(360, 640), const Size(640, 360)]) {
    testWidgets('fixed joystick retains drive and never scrolls at $size', (
      tester,
    ) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      const channel = MethodChannel('motorpi/gamepad');
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        channel,
        (_) async => null,
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          channel,
          null,
        ),
      );
      final link = FakeLink();
      await tester.pumpWidget(controlScreen(link));
      expect(find.byType(SingleChildScrollView), findsNothing);
      expect(tester.getRect(find.text('STOPP')).bottom, lessThan(size.height));
      await tester.tap(find.text('START'));
      await tester.pump();
      final bounds = tester.getRect(find.byType(Joystick));
      final touch = await tester.startGesture(bounds.center);
      await touch.moveTo(bounds.center - Offset(0, bounds.height * .3));
      await tester.pump(const Duration(milliseconds: 100));
      expect(link.driveValues.last.$1, greaterThan(700));
      await touch.up();
      final beforeRelease = link.driveValues.last;
      for (var tick = 0; tick < 120; tick++) {
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(link.driveValues.last, beforeRelease);
      expect(link.commands, isNot(contains(3)));
      expect(tester.getRect(find.byType(Joystick)), bounds);
      await tester.tap(find.text('STOPP'));
      await tester.pump();
      expect(link.commands.last, 3);
      final count = link.driveValues.length;
      await tester.pump(const Duration(seconds: 1));
      expect(link.driveValues.length, count);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }
  testWidgets(
    'Stop stays reachable on a small screen and backgrounding stops control',
    (tester) async {
      tester.view.physicalSize = const Size(360, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      const channel = MethodChannel('motorpi/gamepad');
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        channel,
        (_) async => null,
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          channel,
          null,
        ),
      );
      final link = FakeLink();
      await tester.pumpWidget(controlScreen(link));
      expect(tester.getRect(find.text('STOPP')).bottom, lessThan(640));
      await tester.tap(find.text('START'));
      await tester.pump();
      expect(link.commands, contains(1));
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
      await tester.pump();
      expect(link.commands.last, 3);
      await tester.tap(find.text('STOPP'));
      await tester.pump();
      expect(link.commands.last, 3);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
    },
  );
}
