/// One update from the native Android gamepad adapter (MainActivity.kt).
class GamepadEvent {
  const GamepadEvent({
    required this.name,
    this.connected = true,
    this.start = false,
    this.stop = false,
    this.forward = 0,
    this.steer = 0,
  });

  factory GamepadEvent.fromPlatform(dynamic event) {
    final data = Map<String, dynamic>.from(event as Map);
    return GamepadEvent(
      name: data['name'] as String? ?? 'Kein Controller',
      connected: data['connected'] != false,
      start: data['start'] == true,
      stop: data['stop'] == true,
      forward: (data['forward'] as num? ?? 0).toDouble(),
      steer: (data['steer'] as num? ?? 0).toDouble(),
    );
  }

  final String name;
  final bool connected, start, stop;
  final double forward, steer;
}
