/// Result of one probe connection to a candidate host.
class DiscoveredPi {
  const DiscoveredPi({
    required this.host,
    required this.port,
    this.address,
    this.live = false,
    this.occupied = false,
    this.latency,
    this.error,
  });

  final String host;
  final int port;

  /// Resolved IP; two hostnames for the same Pi collapse into one entry.
  final String? address;
  final bool live;

  /// Another phone holds the control session; the Pi rejected the probe.
  final bool occupied;
  final Duration? latency;
  final String? error;

  bool get reachable => error == null;
  bool get selectable => reachable && !occupied;

  String get modeLabel => !reachable
      ? 'Nicht erreichbar'
      : occupied
      ? 'Belegt (anderes Handy)'
      : live
      ? 'ECHTBETRIEB'
      : 'SIMULATION';
}
