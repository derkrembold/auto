import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:motorpi_control/main.dart';

void main() {
  testWidgets('release retains setpoint; cancellation sends a safety stop', (
    tester,
  ) async {
    final values = <(double, double, bool)>[];
    await tester.pumpWidget(
      MaterialApp(
        home: Center(
          child: Joystick(
            enabled: true,
            onChanged: (f, s, h) => values.add((f, s, h)),
          ),
        ),
      ),
    );
    final center = tester.getCenter(find.byType(Joystick));
    final touch = await tester.startGesture(center);
    await touch.moveTo(center - const Offset(0, 80));
    expect(values.last.$1, greaterThan(.8));
    expect(values.last.$3, isTrue);
    final lastSetpoint = values.last;
    final count = values.length;
    await touch.up();
    expect(values.length, count);
    expect(values.last, lastSetpoint);
    final second = await tester.startGesture(center);
    await second.cancel();
    expect(values.last, (0.0, 0.0, false));
  });
  testWidgets('disabled joystick cannot send motion', (tester) async {
    var calls = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Center(
          child: Joystick(enabled: false, onChanged: (_, _, _) => calls++),
        ),
      ),
    );
    await tester.drag(find.byType(Joystick), const Offset(60, -60));
    expect(calls, 0);
  });
}
