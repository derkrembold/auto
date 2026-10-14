import 'package:flutter/material.dart';
import '../../theme.dart';

class Joystick extends StatefulWidget {
  const Joystick({
    super.key,
    required this.enabled,
    required this.onChanged,
    this.size = 250,
  });
  final bool enabled;
  final double size;
  final void Function(double forward, double steer, bool held) onChanged;
  @override
  State<Joystick> createState() => _JoystickState();
}

class _JoystickState extends State<Joystick> {
  Offset offset = Offset.zero;
  int? pointer;
  void cancel() {
    pointer = null;
    setState(() => offset = Offset.zero);
    widget.onChanged(0, 0, false);
  }

  void update(PointerEvent event) {
    if (!widget.enabled || event.pointer != pointer) return;
    if (widget.size <= 0) return;
    final radius = widget.size * .36;
    var next = event.localPosition - Offset(widget.size / 2, widget.size / 2);
    if (next.distance > radius) next = next / next.distance * radius;
    setState(() => offset = next);
    widget.onChanged(-next.dy / radius, next.dx / radius, true);
  }

  @override
  void didUpdateWidget(Joystick oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.enabled) {
      pointer = null;
      offset = Offset.zero;
    }
  }

  @override
  Widget build(BuildContext context) => Listener(
    onPointerDown: (event) {
      if (widget.enabled && pointer == null) {
        pointer = event.pointer;
        update(event);
      }
    },
    onPointerMove: update,
    onPointerUp: (event) {
      // Keep the visible setpoint and heartbeats until STOPP or a safety stop.
      if (event.pointer == pointer) pointer = null;
    },
    onPointerCancel: (event) {
      if (event.pointer == pointer) cancel();
    },
    child: SizedBox(
      width: widget.size,
      height: widget.size,
      child: CustomPaint(painter: _StickPainter(offset, widget.enabled)),
    ),
  );
}

class _StickPainter extends CustomPainter {
  _StickPainter(this.offset, this.enabled);
  final Offset offset;
  final bool enabled;
  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    final scale = size.width / 250;
    canvas.scale(scale);
    size = const Size(250, 250);
    final center = size.center(Offset.zero);
    canvas.drawCircle(center, 112, Paint()..color = AppColors.stickBase);
    final lines = Paint()
      ..color = AppColors.stickLines
      ..strokeWidth = 1;
    canvas.drawLine(
      center - const Offset(95, 0),
      center + const Offset(95, 0),
      lines,
    );
    canvas.drawLine(
      center - const Offset(0, 95),
      center + const Offset(0, 95),
      lines,
    );
    canvas.drawCircle(center, 70, lines..style = PaintingStyle.stroke);
    canvas.drawCircle(
      center + (scale > 0 ? offset / scale : Offset.zero),
      33,
      Paint()
        ..color = enabled ? AppColors.stickKnob : AppColors.stickKnobDisabled,
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(_StickPainter oldDelegate) =>
      offset != oldDelegate.offset || enabled != oldDelegate.enabled;
}
