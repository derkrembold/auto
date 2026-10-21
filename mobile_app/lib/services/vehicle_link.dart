import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import '../models/protocol.dart';
import 'platform_network.dart';
import 'transport.dart';

class VehicleLink extends ChangeNotifier {
  VehicleLink({Connector? connector, Future<void> Function()? prepareNetwork})
    : _connector = connector ?? SocketTransport.connect,
      _prepareNetwork = prepareNetwork ?? bindWifi;
  final Connector _connector;
  final Future<void> Function() _prepareNetwork;
  Transport? _transport;
  StreamSubscription<List<int>>? _input;
  SessionProtocol? _protocol;
  bool connected = false, connecting = false, busy = false;
  String message = 'Mit dem WLAN „MotorPi“ verbinden.';
  VehicleStatus? status;
  DateTime? lastStatus;

  /// Last Pi this app controlled; probed first by discovery and used by the
  /// log viewer and shell after a drive session ends.
  String? host;
  int _generation = 0;
  bool _disposed = false;
  Completer<void>? _acknowledgement;
  int? _awaitedSequence;
  void _notify() {
    if (!_disposed) notifyListeners();
  }

  Future<void> connect({
    String host = defaultHost,
    int port = defaultPort,
  }) async {
    if (connecting || connected) return;
    var stage = 'Verbinden';
    int? attempt;
    try {
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

      connecting = true;
      progress('WLAN auswählen');
      await _prepareNetwork();
      progress('Pi unter $host erreichen');
      final transport = await _connector(
        host,
        port,
      ).timeout(const Duration(seconds: 6));
      if (generation != _generation || _disposed) {
        await transport.close();
        ensureCurrent();
      }
      _transport = transport;
      final greeted = Completer<void>();
      final claimed = Completer<void>();
      // A rejection may fail a waiter that is not awaited yet; keep it handled.
      greeted.future.ignore();
      claimed.future.ignore();
      final decoder = FrameDecoder();
      void fail(Object error) {
        if (!greeted.isCompleted) greeted.completeError(error);
        if (!claimed.isCompleted) claimed.completeError(error);
      }

      _input = transport.input.listen(
        (bytes) {
          if (generation != _generation) return;
          try {
            for (final frame in decoder.add(bytes)) {
              if (frame.isEmpty) throw const FormatException('Leerer Frame');
              final payload = frame.sublist(1);
              switch (frame[0]) {
                case 0x53: // S
                  status = VehicleStatus(payload);
                  lastStatus = DateTime.now();
                  if (!greeted.isCompleted) greeted.complete();
                  if (status!.claimed &&
                      _protocol != null &&
                      !claimed.isCompleted) {
                    claimed.complete();
                  }
                  if (status!.ack == _awaitedSequence &&
                      !(_acknowledgement?.isCompleted ?? true)) {
                    _acknowledgement!.complete();
                  }
                case 0x45: // E
                  final reason = utf8.decode(payload, allowMalformed: true);
                  final error = StateError('Pi: $reason');
                  if (connected) {
                    _lost('Vom Pi abgelehnt: $reason');
                  } else {
                    fail(error);
                  }
                default:
                  throw const FormatException('Unbekannter Frame');
              }
            }
            _notify();
          } catch (error) {
            if (connected) {
              _lost('Ungültige Daten vom Pi: $error');
            } else {
              fail(error);
            }
          }
        },
        onError: (Object error) {
          if (generation != _generation) return;
          if (connected) {
            _lost('WLAN-Verbindung unterbrochen: $error');
          } else {
            fail(error);
          }
        },
        onDone: () {
          if (generation != _generation) return;
          if (connected) {
            _lost('WLAN-Verbindung zum Pi getrennt.');
          } else {
            fail(StateError('Pi hat die Verbindung geschlossen'));
          }
        },
      );
      progress('Status vom Pi lesen');
      await greeted.future.timeout(const Duration(seconds: 5));
      ensureCurrent();
      _protocol = SessionProtocol();
      progress('Steuerung übernehmen');
      transport.add(encodeFrame(_protocol!.claim()));
      await claimed.future.timeout(const Duration(seconds: 5));
      ensureCurrent();
      connected = true;
      connecting = false;
      this.host = host;
      message = 'Verbunden · Start gibt die Steuerung frei.';
      _notify();
    } catch (error) {
      // A canceled/failed attempt must not tear down a later connection.
      if (attempt != null && attempt != _generation) return;
      await disconnect();
      message = error is TimeoutException
          ? 'Zeitüberschreitung: $stage. Mit WLAN „MotorPi“ verbinden und erneut versuchen.'
          : '$stage fehlgeschlagen: ${error is StateError ? error.message : error}';
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
    if (!connected || busy || _protocol == null || _transport == null) {
      return false;
    }
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
      // Install the waiter before writing; one command at a time, no backlog.
      _transport!.add(encodeFrame(value));
      await acknowledgement.future.timeout(const Duration(milliseconds: 500));
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
    unawaited(_input?.cancel());
    unawaited(_transport?.close());
    _input = null;
    _transport = null;
    _notify();
  }

  Future<void> disconnect() async {
    if (connected) message = 'Verbindung getrennt.';
    connected = false;
    connecting = false;
    ++_generation;
    await _input?.cancel();
    await _transport?.close();
    _input = null;
    _transport = null;
    _protocol = null;
    status = null;
    _notify();
  }

  @override
  void dispose() {
    _disposed = true;
    unawaited(disconnect());
    super.dispose();
  }
}
