import 'package:flutter/foundation.dart';
import 'models/protocol.dart';

/// Debug builds only: `flutter run --dart-define=MOTORPI_CODE=ABCD2345` skips
/// the access-code screen. The Pi still verifies the code; nothing is stored.
const _debugAccessCode = String.fromEnvironment('MOTORPI_CODE');
String? get debugAccessCode =>
    kDebugMode && _debugAccessCode.isNotEmpty ? _debugAccessCode : null;

/// The read-only log service next to the control server (raspi/mobile/log_server.py).
const logPort = 8081;
const sshPort = 22;

/// Probe order: last used host first, then the access point, then mDNS on a LAN.
const fallbackHosts = [defaultHost, 'motorpi.local'];
