import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../../controllers/drive_controller.dart';
import '../../theme.dart';

class DriveButtons extends StatelessWidget {
  const DriveButtons({super.key});
  @override
  Widget build(BuildContext context) {
    final drive = context.watch<DriveController>();
    return Row(
      children: [
        Expanded(
          child: FilledButton.icon(
            onPressed: drive.canStart ? drive.start : null,
            icon: const Icon(Icons.play_arrow),
            label: const Text('START'),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: FilledButton.icon(
            style: stopButtonStyle,
            onPressed: drive.stop,
            icon: const Icon(Icons.stop),
            label: const Text('STOPP'),
          ),
        ),
      ],
    );
  }
}
