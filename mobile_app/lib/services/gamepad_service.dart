import 'package:flutter/services.dart';
import '../models/gamepad_event.dart';

const _channel = EventChannel('motorpi/gamepad');

/// Native gamepad input; a fresh listen re-emits the current controller name.
Stream<GamepadEvent> gamepadEvents() =>
    _channel.receiveBroadcastStream().map(GamepadEvent.fromPlatform);
