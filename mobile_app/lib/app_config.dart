import 'models/protocol.dart';

/// The read-only log service next to the control server (raspi/mobile/log_server.py).
const logPort = 8081;
const sshPort = 22;

/// Probe order: last used host first, then the access point, then mDNS on a LAN.
const fallbackHosts = [defaultHost, 'motorpi.local'];
