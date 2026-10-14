import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_reactive_ble/flutter_reactive_ble.dart';
import 'protocol.dart';

class VehicleLink extends ChangeNotifier {
  VehicleLink({FlutterReactiveBle? ble}) : _injectedBle = ble;
  final FlutterReactiveBle? _injectedBle;
  late final _ble = _injectedBle ?? FlutterReactiveBle();
  static const platform = MethodChannel('motorpi/platform');
  final devices = <String, DiscoveredDevice>{};
  StreamSubscription<DiscoveredDevice>? _scan;
  StreamSubscription<ConnectionStateUpdate>? _connection;
  StreamSubscription<List<int>>? _notifications;
  SessionProtocol? _protocol;
  String? _device;
  bool scanning = false, connected = false, connecting = false, busy = false;
  String message = 'Verbinde dich mit deinem MotorPi.';
  VehicleStatus? status;
  DateTime? lastStatus;
  int _generation = 0;
  bool _disposed = false;
  Completer<void>? _acknowledgement;
  int? _awaitedSequence;
  void _notify() {
    if (!_disposed) notifyListeners();
  }

  QualifiedCharacteristic _characteristic(String uuid) =>
      QualifiedCharacteristic(
        characteristicId: Uuid.parse(uuid),
        serviceId: Uuid.parse(serviceUuid),
        deviceId: _device!,
      );

  Future<void> scan() async {
    try {
      final granted =
          await platform.invokeMethod<bool>('bluetoothPermissions') ?? false;
      if (!granted) {
        throw StateError('Bluetooth-Berechtigung wurde nicht erteilt.');
      }
      if (_ble.status != BleStatus.ready) {
        await _ble.statusStream
            .firstWhere((s) => s == BleStatus.ready)
            .timeout(const Duration(seconds: 8));
      }
      await _scan?.cancel();
      devices.clear();
      scanning = true;
      message = 'Suche MotorPi …';
      _notify();
      _scan = _ble
          .scanForDevices(
            withServices: [Uuid.parse(serviceUuid)],
            scanMode: ScanMode.lowLatency,
          )
          .listen(
            (device) {
              devices[device.id] = device;
              _notify();
            },
            onError: (Object error) {
              message = 'Bluetooth-Suche: $error';
              scanning = false;
              _notify();
            },
          );
    } catch (error) {
      message = 'Bluetooth einschalten und Berechtigungen prüfen: $error';
      _notify();
    }
  }

  Future<void> connect(DiscoveredDevice device, String keyText) async {
    if (connecting || connected) return;
    var stage = 'Zugangscode prüfen';
    int? attempt;
    try {
      final key = parseKey(keyText);
      await disconnect();
      final generation = ++_generation;
      attempt = generation;
      void ensureCurrent() {
        if (generation != _generation || _disposed) {
          throw StateError('Verbindung wurde beendet');
        }
      }

      void progress(String step) {
        ensureCurrent();
        stage = step;
        message = '$step …';
        _notify();
      }

      await _scan?.cancel();
      scanning = false;
      connecting = true;
      _device = device.id;
      message = 'Verbinde mit ${device.name} …';
      _notify();
      final established = Completer<void>();
      stage = 'Bluetooth verbinden';
      _connection = _ble
          .connectToDevice(
            id: device.id,
            connectionTimeout: const Duration(seconds: 10),
          )
          .listen(
            (update) {
              if (generation != _generation) return;
              if (update.connectionState == DeviceConnectionState.connected &&
                  !established.isCompleted) {
                established.complete();
              }
              if (update.connectionState ==
                  DeviceConnectionState.disconnected) {
                if (!established.isCompleted) {
                  established.completeError(StateError('Verbindung getrennt'));
                }
                _lost('Bluetooth-Verbindung getrennt.');
              }
            },
            onError: (Object error) {
              if (!established.isCompleted) established.completeError(error);
              if (generation == _generation) _lost('Bluetooth: $error');
            },
          );
      await established.future.timeout(const Duration(seconds: 12));
      // Android's first GATT read includes service discovery unless performed
      // explicitly. Discovery must not consume the short command deadline.
      progress('Bluetooth-Dienste suchen');
      await _ble
          .discoverAllServices(device.id)
          .timeout(const Duration(seconds: 15));
      progress('Sitzung vom Pi lesen');
      final nonce = await _ble
          .readCharacteristic(_characteristic(challengeUuid))
          .timeout(const Duration(seconds: 8));
      ensureCurrent();
      _protocol = SessionProtocol(key, nonce);
      progress('Statuskanal öffnen');
      final firstStatus = Completer<void>();
      final authenticated = Completer<void>();
      _notifications = _ble
          .subscribeToCharacteristic(_characteristic(statusUuid))
          .listen(
            (bytes) {
              if (generation != _generation) return;
              try {
                status = VehicleStatus(bytes);
                lastStatus = DateTime.now();
                if (!firstStatus.isCompleted) firstStatus.complete();
                if (status!.authenticated && !authenticated.isCompleted) {
                  authenticated.complete();
                }
                if (status!.ack == _awaitedSequence &&
                    !(_acknowledgement?.isCompleted ?? true)) {
                  _acknowledgement!.complete();
                }
                _notify();
              } catch (error) {
                _lost('Ungültiger Status: $error');
              }
            },
            onError: (Object error) {
              if (generation == _generation) {
                _lost('Statusverbindung unterbrochen: $error');
              }
            },
          );
      // Complete Android's notification/CCC setup before starting another GATT
      // operation. Notifications also acknowledge authentication; avoid racing
      // a status read against an outstanding subscription or authentication.
      await firstStatus.future.timeout(const Duration(seconds: 10));
      progress('Anmeldung senden');
      await _ble
          .writeCharacteristicWithoutResponse(
            _characteristic(commandUuid),
            value: _protocol!.authentication(),
          )
          .timeout(const Duration(seconds: 8));
      progress('Anmeldung bestätigen');
      await authenticated.future.timeout(const Duration(seconds: 5));
      ensureCurrent();
      connected = true;
      connecting = false;
      message = 'Verbunden · Start gibt die Steuerung frei.';
      _notify();
    } catch (error) {
      // A canceled/failed attempt must not tear down a later connection or
      // replace the more specific disconnect/notification error message.
      if (attempt != null && attempt != _generation) return;
      await disconnect();
      message = error is TimeoutException
          ? 'Zeitüberschreitung: $stage. ${stage == 'Anmeldung bestätigen' ? 'Der Pi hat die Anmeldung nicht bestätigt; Verbindung und Zugangscode prüfen.' : 'Bluetooth-Verbindung prüfen und erneut verbinden.'}'
          : '$stage fehlgeschlagen: $error';
      _notify();
    }
  }

  Future<bool> send(
    int operation, {
    int forward = 0,
    int steer = 0,
    bool held = false,
    int speedLimit = 100,
  }) async {
    if (!connected || busy || _protocol == null) return false;
    busy = true;
    try {
      final value = _protocol!.command(
        operation,
        forward: forward,
        steer: steer,
        held: held,
        speedLimit: speedLimit,
      );
      _awaitedSequence = _protocol!.sequence;
      final acknowledgement = _acknowledgement = Completer<void>();
      // Install the listener before writing: a notification may arrive before
      // the platform write Future completes. One command at a time, no backlog.
      await _ble
          .writeCharacteristicWithoutResponse(
            _characteristic(commandUuid),
            value: value,
          )
          .then((_) => acknowledgement.future)
          .timeout(const Duration(milliseconds: 500));
      return connected;
    } catch (error) {
      _lost('Steuerung unterbrochen: $error');
      return false;
    } finally {
      _acknowledgement = null;
      _awaitedSequence = null;
      busy = false;
    }
  }

  void _lost(String reason) {
    connected = false;
    connecting = false;
    status = null;
    message = reason;
    _protocol = null;
    ++_generation;
    unawaited(_notifications?.cancel());
    unawaited(_connection?.cancel());
    _notifications = null;
    _connection = null;
    _notify();
  }

  Future<void> disconnect() async {
    connected = false;
    connecting = false;
    ++_generation;
    await _notifications?.cancel();
    await _connection?.cancel();
    _notifications = null;
    _connection = null;
    _protocol = null;
    status = null;
    _notify();
  }

  @override
  void dispose() {
    _disposed = true;
    unawaited(_scan?.cancel());
    unawaited(disconnect());
    super.dispose();
  }
}
