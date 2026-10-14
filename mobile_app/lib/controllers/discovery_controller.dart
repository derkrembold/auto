import 'package:flutter/foundation.dart';
import '../app_config.dart';
import '../models/discovered_pi.dart';
import '../routes.dart';
import '../services/pi_discovery.dart';
import '../services/platform_network.dart' as network;
import '../services/vehicle_link.dart';

class DiscoveryController extends ChangeNotifier {
  DiscoveryController({
    required this.discovery,
    required this.link,
    this.autoSelect = false,
    this.accessCode,
    Future<void> Function()? prepareNetwork,
  }) : _prepareNetwork = prepareNetwork ?? network.bindWifi;
  final Future<void> Function() _prepareNetwork;
  final PiDiscovery discovery;
  final VehicleLink link;

  /// Only right after launch: one free Pi found means go straight on. After a
  /// connection loss the user decides, so a rejecting Pi cannot cause a loop.
  bool autoSelect;

  /// Defaults to [debugAccessCode]; injectable for tests.
  final String? accessCode;
  final _manualHosts = <String>[];
  List<DiscoveredPi> results = [];
  bool scanning = false, selecting = false;
  String? networkError;

  List<String> get candidates => {
    if (link.host != null) link.host!,
    ...fallbackHosts,
    ..._manualHosts,
  }.toList();

  /// Host for logs/shell before any Pi was selected.
  String get bestHost =>
      results.where((pi) => pi.reachable).firstOrNull?.host ??
      link.host ??
      fallbackHosts.first;

  Future<void> scan() async {
    if (scanning) return;
    scanning = true;
    networkError = null;
    notifyListeners();
    try {
      await _prepareNetwork();
    } catch (e) {
      // Still probe: on a LAN without the AP the Pi may be reachable anyway.
      networkError = e is StateError ? e.message : '$e';
    }
    results = await discovery.scan(candidates);
    scanning = false;
    notifyListeners();
  }

  void addHost(String host) {
    final trimmed = host.trim();
    if (trimmed.isEmpty || candidates.contains(trimmed)) return;
    _manualHosts.add(trimmed);
    notifyListeners();
  }

  /// The single free Pi to continue with automatically, if any.
  DiscoveredPi? takeAutoSelection() {
    if (!autoSelect) return null;
    autoSelect = false;
    final free = results.where((pi) => pi.selectable).toList();
    return free.length == 1 ? free.single : null;
  }

  /// Returns the next route: straight to the drive screen when a debug code
  /// is configured and accepted, else the access-code screen.
  Future<String> select(DiscoveredPi pi) async {
    final code = accessCode ?? debugAccessCode;
    if (code == null) return Routes.accessCode;
    selecting = true;
    notifyListeners();
    await link.connect(code, host: pi.host, port: pi.port);
    selecting = false;
    notifyListeners();
    return link.connected ? Routes.control : Routes.accessCode;
  }
}
