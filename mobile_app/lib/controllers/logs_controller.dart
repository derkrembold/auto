import 'dart:io';
import 'package:flutter/foundation.dart';
import '../app_config.dart';
import '../models/protocol.dart';
import '../services/log_client.dart';

typedef LogClientFactory = LogClient Function(String host, List<int> key);

class LogsController extends ChangeNotifier {
  LogsController({required this.host, List<int>? key, LogClientFactory? client})
    : _factory = client ?? ((host, key) => LogClient(host: host, key: key)) {
    final code = debugAccessCode;
    if (key != null) {
      _client = _factory(host, key);
    } else if (code != null) {
      unlock(code);
    }
  }
  final String host;
  final LogClientFactory _factory;
  LogClient? _client;
  List<LogSource> sources = [];
  String? selected;
  int lines = 200;
  String text = '';
  String? error;
  bool loading = false;

  /// Logs need the access code; after a drive session the app already has it.
  bool get locked => _client == null;

  void unlock(String code) {
    try {
      _client = _factory(host, parseKey(code));
      error = null;
    } on FormatException catch (e) {
      error = e.message;
    }
    notifyListeners();
  }

  Future<void> loadSources() => _run(() async {
    sources = await _client!.sources();
    selected ??= sources.where((s) => s.available).firstOrNull?.name;
    if (selected != null) text = await _client!.fetch(selected!, lines: lines);
  });

  Future<void> select(String name) {
    selected = name;
    return refresh();
  }

  Future<void> setLines(int value) {
    lines = value;
    return refresh();
  }

  Future<void> refresh() => _run(() async {
    if (selected != null) text = await _client!.fetch(selected!, lines: lines);
  });

  Future<void> _run(Future<void> Function() action) async {
    if (_client == null || loading) return;
    loading = true;
    error = null;
    notifyListeners();
    try {
      await action();
    } catch (e) {
      error = switch (e) {
        SocketException() =>
          'Log-Dienst auf $host:$logPort nicht erreichbar (${e.message}).',
        HttpException(message: final message)
            when message.startsWith('Pi 403') =>
          _relock('Zugangscode abgelehnt.'),
        _ => '$e',
      };
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  /// A rejected code goes back to the code form instead of a dead end.
  String _relock(String reason) {
    _client?.close();
    _client = null;
    return reason;
  }

  @override
  void dispose() {
    _client?.close();
    super.dispose();
  }
}
