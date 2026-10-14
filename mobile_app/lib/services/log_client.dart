import 'dart:convert';
import 'dart:io';
import 'package:crypto/crypto.dart';
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

/// Read-only client for raspi/mobile/log_server.py. Every request first takes
/// a single-use challenge, then proves the access code with
/// HMAC-SHA256(key, "logs" || nonce || path)[:16].
class LogClient {
  LogClient({required this.host, required this.key, this.port = logPort});
  final String host;
  final int port;
  final List<int> key;
  final _http = HttpClient()..connectionTimeout = const Duration(seconds: 5);

  Future<List<LogSource>> sources() async {
    final body = await _get('/logs');
    return [
      for (final item in jsonDecode(body) as List)
        LogSource.fromJson(item as Map<String, dynamic>),
    ];
  }

  Future<String> fetch(String name, {int lines = 200}) =>
      _get('/logs/${Uri.encodeComponent(name)}?lines=$lines');

  Future<String> _get(String pathAndQuery) async {
    final challenge = jsonDecode(await _request('/challenge')) as Map;
    final nonce = _hex(challenge['nonce'] as String);
    final mac = Hmac(sha256, key)
        .convert([
          ...utf8.encode('logs'),
          ...nonce,
          ...utf8.encode(pathAndQuery),
        ])
        .bytes
        .take(16);
    return _request(
      pathAndQuery,
      auth:
          '${challenge['nonce']}:${mac.map((b) => b.toRadixString(16).padLeft(2, '0')).join()}',
    );
  }

  Future<String> _request(String pathAndQuery, {String? auth}) async {
    final request = await _http
        .getUrl(Uri.parse('http://$host:$port$pathAndQuery'))
        .timeout(const Duration(seconds: 6));
    if (auth != null) request.headers.set('X-MotorPi-Auth', auth);
    final response = await request.close().timeout(const Duration(seconds: 10));
    final body = await response.transform(utf8.decoder).join();
    if (response.statusCode != 200) {
      throw HttpException('Pi ${response.statusCode}: ${body.trim()}');
    }
    return body;
  }

  static List<int> _hex(String text) => [
    for (var i = 0; i + 1 < text.length; i += 2)
      int.parse(text.substring(i, i + 2), radix: 16),
  ];

  void close() => _http.close(force: true);
}
