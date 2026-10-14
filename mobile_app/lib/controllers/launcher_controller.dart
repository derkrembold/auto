import 'package:flutter/foundation.dart';
import '../services/platform_network.dart' as network;

/// Binds the app to the WLAN before anything tries to reach the Pi.
class LauncherController extends ChangeNotifier {
  LauncherController({Future<void> Function()? prepareNetwork})
    : _prepareNetwork = prepareNetwork ?? network.bindWifi;
  final Future<void> Function() _prepareNetwork;
  bool busy = false;
  String? error;

  /// True when the WLAN is bound and discovery can start.
  Future<bool> prepare() async {
    busy = true;
    error = null;
    notifyListeners();
    try {
      await _prepareNetwork();
      return true;
    } catch (e) {
      error = e is StateError ? e.message : '$e';
      return false;
    } finally {
      busy = false;
      notifyListeners();
    }
  }
}
