import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:motorpi_control/services/log_client.dart';

void main() {
  test(
    'lists sources and tails a log like log_server.py serves them',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final seen = <String>[];
      server.listen((request) async {
        seen.add('${request.uri}');
        request.response.write(
          request.uri.path == '/logs'
              ? jsonEncode([
                  {'name': 'watchdog', 'label': 'Watchdog', 'available': true},
                ])
              : 'line 1\n',
        );
        await request.response.close();
      });
      final client = LogClient(host: '127.0.0.1', port: server.port);
      expect((await client.sources()).single.name, 'watchdog');
      expect(await client.fetch('watchdog'), 'line 1\n');
      expect(seen, ['/logs', '/logs/watchdog?lines=200']);
      client.close();
      await server.close(force: true);
    },
  );

  test('a rejected request surfaces the Pi reason', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    server.listen((request) async {
      request.response
        ..statusCode = 404
        ..write('Unknown log source');
      await request.response.close();
    });
    final client = LogClient(host: '127.0.0.1', port: server.port);
    await expectLater(
      client.fetch('nope'),
      throwsA(
        isA<HttpException>().having(
          (e) => e.message,
          'message',
          'Pi 404: Unknown log source',
        ),
      ),
    );
    client.close();
    await server.close(force: true);
  });
}
