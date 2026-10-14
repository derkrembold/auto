import 'package:flutter/material.dart';

abstract final class AppColors {
  static const seed = Color(0xff67e5b0);
  static const background = Color(0xff101817);
  static const stop = Color(0xffbf3e39);
  static const onStop = Colors.white;
  static const warning = Colors.orange;
  static const muted = Colors.white60;
  static const stickBase = Color(0xff1c2b27);
  static const stickLines = Color(0xff3d5149);
  static const stickKnob = seed;
  static const stickKnobDisabled = Color(0xff66766e);
  static const terminalBackground = Color(0xff0b100f);
}

ThemeData buildTheme() => ThemeData(
  useMaterial3: true,
  brightness: Brightness.dark,
  colorScheme: ColorScheme.fromSeed(
    seedColor: AppColors.seed,
    brightness: Brightness.dark,
  ),
  scaffoldBackgroundColor: AppColors.background,
  inputDecorationTheme: const InputDecorationTheme(
    border: OutlineInputBorder(),
  ),
);

/// The red STOPP button style; shared by the drive screen and nothing else on purpose.
final ButtonStyle stopButtonStyle = FilledButton.styleFrom(
  backgroundColor: AppColors.stop,
  foregroundColor: AppColors.onStop,
  padding: const EdgeInsets.symmetric(vertical: 20),
);
