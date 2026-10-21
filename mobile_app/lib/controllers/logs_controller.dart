import 'dart:io';
import 'package:flutter/foundation.dart';
import '../app_config.dart';
import '../services/log_client.dart';

/// No access code: the Pi serves logs to any phone on the MotorPi WLAN.
class LogsController extends ChangeNotifier {
  LogsController({required this.host, LogClient? client})
    : _client = client ?? LogClient(host: host);
  final String host;
  final LogClient _client;
  List<LogSource> sources = [];
  String? selected;
  int lines = 200;
  String text = '';
  String? error;
  bool loading = false;

  Future<void> loadSources() => _run(() async {
    sources = await _client.sources();
    selected ??= sources.where((s) => s.available).firstOrNull?.name;
    if (selected != null) text = await _client.fetch(selected!, lines: lines);
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
    if (selected != null) text = await _client.fetch(selected!, lines: lines);
  });

  Future<void> _run(Future<void> Function() action) async {
    if (loading) return;
    loading = true;
    error = null;
    notifyListeners();
    try {
      await action();
    } catch (e) {
      error = switch (e) {
        SocketException() =>
          'Log-Dienst auf $host:$logPort nicht erreichbar (${e.message}). '
              'Logs gibt es nur im WLAN „MotorPi“.',
        _ => '$e',
      };
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  @override
  void dispose() {
    _client.close();
    super.dispose();
  }
}
