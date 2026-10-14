import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'protocol.dart';

/// A byte stream to the Pi. Production uses TCP over the MotorPi WLAN.
abstract class Transport {
  Stream<List<int>> get input;
  void add(List<int> bytes);
  Future<void> close();
}

class SocketTransport implements Transport {
  SocketTransport(this._socket) {
    _socket.setOption(SocketOption.tcpNoDelay, true);
  }
  final Socket _socket;
  static Future<Transport> connect(String host, int port) async =>
      SocketTransport(
        await Socket.connect(host, port, timeout: const Duration(seconds: 5)),
      );
  @override
  Stream<List<int>> get input => _socket;
  @override
  void add(List<int> bytes) => _socket.add(bytes);
  @override
  Future<void> close() async => _socket.destroy();
}

typedef Connector = Future<Transport> Function(String host, int port);

class VehicleLink extends ChangeNotifier {
  VehicleLink({Connector? connector, Future<void> Function()? prepareNetwork})
    : _connector = connector ?? SocketTransport.connect,
      _prepareNetwork = prepareNetwork ?? _bindWifi;
  final Connector _connector;
  final Future<void> Function() _prepareNetwork;
  static const platform = MethodChannel('motorpi/platform');
  Transport? _transport;
  StreamSubscription<List<int>>? _input;
  SessionProtocol? _protocol;
  bool connected = false, connecting = false, busy = false;
  String message =
      'Mit dem WLAN „MotorPi“ verbinden, dann Zugangscode eingeben.';
  VehicleStatus? status;
  DateTime? lastStatus;
  int _generation = 0;
  bool _disposed = false;
  Completer<void>? _acknowledgement;
  int? _awaitedSequence;
  void _notify() {
    if (!_disposed) notifyListeners();
  }

  /// Android routes sockets via mobile data when the WLAN has no internet;
  /// binding the process to the WLAN keeps 10.42.0.1 reachable.
  static Future<void> _bindWifi() async {
    final bound = await platform.invokeMethod<bool>('bindWifi') ?? false;
    if (!bound) {
      throw StateError('Kein WLAN verbunden. Mit „MotorPi“ verbinden.');
    }
  }

  Future<void> connect(
    String keyText, {
    String host = defaultHost,
    int port = defaultPort,
  }) async {
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
      final challenge = Completer<List<int>>();
      final authenticated = Completer<void>();
      // A rejection may fail a waiter that is not awaited yet; keep it handled.
      challenge.future.ignore();
      authenticated.future.ignore();
      final decoder = FrameDecoder();
      void fail(Object error) {
        if (!challenge.isCompleted) challenge.completeError(error);
        if (!authenticated.isCompleted) authenticated.completeError(error);
      }

      _input = transport.input.listen(
        (bytes) {
          if (generation != _generation) return;
          try {
            for (final frame in decoder.add(bytes)) {
              if (frame.isEmpty) throw const FormatException('Leerer Frame');
              final payload = frame.sublist(1);
              switch (frame[0]) {
                case 0x43: // C
                  if (!challenge.isCompleted) challenge.complete(payload);
                case 0x53: // S
                  status = VehicleStatus(payload);
                  lastStatus = DateTime.now();
                  if (status!.authenticated &&
                      _protocol != null &&
                      !authenticated.isCompleted) {
                    authenticated.complete();
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
      progress('Sitzung vom Pi lesen');
      final nonce = await challenge.future.timeout(const Duration(seconds: 5));
      ensureCurrent();
      _protocol = SessionProtocol(key, nonce);
      progress('Anmeldung senden');
      transport.add(encodeFrame(_protocol!.authentication()));
      progress('Anmeldung bestätigen');
      await authenticated.future.timeout(const Duration(seconds: 5));
      ensureCurrent();
      connected = true;
      connecting = false;
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
