import 'dart:async';
import 'package:flutter/widgets.dart';
import '../models/gamepad_event.dart';
import '../services/gamepad_service.dart';
import '../services/vehicle_link.dart';

/// Arming, the 100 ms drive heartbeat and every app-side safety stop.
/// Lives exactly as long as the drive screen.
class DriveController extends ChangeNotifier with WidgetsBindingObserver {
  DriveController({required this.link, Stream<GamepadEvent>? gamepad}) {
    WidgetsBinding.instance.addObserver(this);
    link.addListener(_onLink);
    _gamepad = (gamepad ?? gamepadEvents()).listen(
      _onGamepad,
      onError: (Object _) {
        if (useGamepad) unawaited(stop());
      },
    );
    _timer = Timer.periodic(const Duration(milliseconds: 100), (_) => _tick());
  }

  final VehicleLink link;
  late final Timer _timer;
  late final StreamSubscription<GamepadEvent> _gamepad;
  bool armed = false, held = false, useGamepad = false, stopping = false;
  double forward = 0, steer = 0, limit = 0.6;
  String controllerName = 'Kein Controller';
  bool _suspended = false, _disposed = false;

  bool get canStart {
    final status = link.status;
    return !(armed ||
        stopping ||
        held ||
        _suspended ||
        status?.ready != true ||
        status?.state == 2 ||
        status?.state == 3);
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  void _onLink() {
    if (!link.connected || link.status?.state != 1) {
      armed = false;
      held = false;
      forward = steer = 0;
    }
    _notify();
  }

  /// Touch joystick input; a cancelled gesture (`active == false`) stops.
  void setJoystick(double f, double s, bool active) {
    final wasHeld = held;
    forward = f;
    steer = s;
    held = active;
    _notify();
    if (!active && wasHeld && armed) unawaited(stop());
  }

  void _onGamepad(GamepadEvent event) {
    if (_disposed) return;
    controllerName = event.name;
    _notify();
    if (!useGamepad || _suspended) return;
    if (event.stop || !event.connected) {
      unawaited(stop());
      return;
    }
    final f = event.forward, s = event.steer;
    if (event.start && f.abs() < .08 && s.abs() < .08) {
      unawaited(start());
      return;
    }
    // A spring-centred controller retains the last non-neutral setpoint too.
    if (armed && (f.abs() >= .08 || s.abs() >= .08)) setJoystick(f, s, true);
  }

  Future<void> setUseGamepad(bool value) async {
    await stop();
    useGamepad = value;
    _notify();
  }

  void setLimit(double value) {
    if (armed) return;
    limit = value;
    _notify();
  }

  Future<void> start() async {
    if (held ||
        forward.abs() > .08 ||
        steer.abs() > .08 ||
        stopping ||
        _suspended ||
        link.status?.ready != true) {
      return;
    }
    final ok = await link.send(1);
    if (!_disposed && ok && !stopping && !_suspended && link.connected) {
      armed = true;
      _notify();
    }
  }

  Future<void> stop() async {
    if (_disposed || stopping) return;
    armed = false;
    held = false;
    forward = steer = 0;
    stopping = true;
    _notify();
    await _sendStop();
    stopping = false;
    _notify();
  }

  /// Do not queue drive packets behind a stalled radio. Stop follows at most
  /// one in-flight write; if it cannot be delivered, closing the socket makes
  /// the Pi stop instead.
  Future<void> _sendStop() async {
    final deadline = DateTime.now().add(const Duration(milliseconds: 550));
    while (link.busy && DateTime.now().isBefore(deadline)) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }
    if (link.connected && (link.busy || !await link.send(3))) {
      await link.disconnect();
    }
  }

  /// Stops and blocks starting while another screen (logs, shell) covers the
  /// drive screen, so a gamepad cannot arm the vehicle out of sight.
  Future<T?> suspendWhile<T>(Future<T?> Function() covered) async {
    _suspended = true;
    await stop();
    try {
      return await covered();
    } finally {
      _suspended = false;
      _notify();
    }
  }

  void _tick() {
    if (!armed || !link.connected || stopping) return;
    final now = DateTime.now();
    if (link.lastStatus == null ||
        now.difference(link.lastStatus!).inMilliseconds > 1000) {
      unawaited(stop());
      return;
    }
    unawaited(
      link.send(
        2,
        forward: (forward * 1000).round(),
        steer: (steer * 1000).round(),
        held: held,
        speedLimit: (limit * 100).round(),
      ),
    );
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed) unawaited(stop());
  }

  @override
  void dispose() {
    _disposed = true;
    _timer.cancel();
    WidgetsBinding.instance.removeObserver(this);
    unawaited(_gamepad.cancel());
    link.removeListener(_onLink);
    // The link outlives this screen; never leave the Pi armed behind it, even
    // when a drive packet is still in flight.
    if (armed && link.connected) unawaited(_sendStop());
    super.dispose();
  }
}
