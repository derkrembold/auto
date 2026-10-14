import 'dart:io';

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
