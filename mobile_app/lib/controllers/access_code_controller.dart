import 'package:flutter/foundation.dart';
import '../models/protocol.dart';
import '../services/vehicle_link.dart';

class AccessCodeController extends ChangeNotifier {
  AccessCodeController({
    required this.link,
    required this.host,
    this.port = defaultPort,
  }) {
    link.addListener(notifyListeners);
  }
  final VehicleLink link;
  final String host;
  final int port;

  bool get connecting => link.connecting;
  String get message => link.message;

  /// True once authenticated; the Pi verifies the code, not the app.
  Future<bool> submit(String code) async {
    await link.connect(code, host: host, port: port);
    return link.connected;
  }

  @override
  void dispose() {
    link.removeListener(notifyListeners);
    super.dispose();
  }
}
