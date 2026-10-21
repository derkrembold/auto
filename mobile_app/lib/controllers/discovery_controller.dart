import 'package:flutter/foundation.dart';
import '../app_config.dart';
import '../models/discovered_pi.dart';
import '../services/pi_discovery.dart';
import '../services/platform_network.dart' as network;
import '../services/vehicle_link.dart';

class DiscoveryController extends ChangeNotifier {
  DiscoveryController({
    required this.discovery,
    required this.link,
    this.autoSelect = false,
    Future<void> Function()? prepareNetwork,
  }) : _prepareNetwork = prepareNetwork ?? network.bindWifi;
  final Future<void> Function() _prepareNetwork;
  final PiDiscovery discovery;
  final VehicleLink link;

  /// Only right after launch: one free Pi found means go straight on. After a
  /// connection loss the user decides, so a rejecting Pi cannot cause a loop.
  bool autoSelect;

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

  /// No access code: being on the MotorPi WLAN is enough. True once this
  /// phone controls the Pi; otherwise [VehicleLink.message] says why not.
  Future<bool> select(DiscoveredPi pi) async {
    selecting = true;
    notifyListeners();
    await link.connect(host: pi.host, port: pi.port);
    selecting = false;
    notifyListeners();
    return link.connected;
  }
}
