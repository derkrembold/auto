import 'dart:convert';
import 'dart:io';
import '../app_config.dart';

class LogSource {
  const LogSource(this.name, this.label, this.available);
  factory LogSource.fromJson(Map<String, dynamic> json) => LogSource(
    json['name'] as String,
    json['label'] as String? ?? json['name'] as String,
    json['available'] as bool? ?? true,
  );
  final String name, label;
  final bool available;
}

/// Read-only client for raspi/mobile/log_server.py. No access code; the Pi
/// only answers phones on the MotorPi WLAN.
class LogClient {
  LogClient({required this.host, this.port = logPort});
  final String host;
  final int port;
  final _http = HttpClient()..connectionTimeout = const Duration(seconds: 5);

  Future<List<LogSource>> sources() async {
    final body = await _request('/logs');
    return [
      for (final item in jsonDecode(body) as List)
        LogSource.fromJson(item as Map<String, dynamic>),
    ];
  }

  Future<String> fetch(String name, {int lines = 200}) =>
      _request('/logs/${Uri.encodeComponent(name)}?lines=$lines');

  Future<String> _request(String pathAndQuery) async {
    final request = await _http
        .getUrl(Uri.parse('http://$host:$port$pathAndQuery'))
        .timeout(const Duration(seconds: 6));
    final response = await request.close().timeout(const Duration(seconds: 10));
    final body = await response.transform(utf8.decoder).join();
    if (response.statusCode != 200) {
      throw HttpException('Pi ${response.statusCode}: ${body.trim()}');
    }
    return body;
  }

  void close() => _http.close(force: true);
}
