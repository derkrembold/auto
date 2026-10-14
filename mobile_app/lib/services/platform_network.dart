import 'package:flutter/services.dart';

const _platform = MethodChannel('motorpi/platform');

/// Android routes sockets via mobile data when the WLAN has no internet;
/// binding the process to the WLAN keeps 10.42.0.1 reachable.
Future<void> bindWifi() async {
  final bound = await _platform.invokeMethod<bool>('bindWifi') ?? false;
  if (!bound) {
    throw StateError('Kein WLAN verbunden. Mit „MotorPi“ verbinden.');
  }
}
