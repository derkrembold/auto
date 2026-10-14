import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:motorpi_control/services/log_client.dart';

/// Same vector as raspi/mobile/tests/test_log_server.py.
const golden = 'ed7e8826e793b78dc19da8b3586f91de';

void main() {
  test(
    'signs each request with a fresh challenge like log_server.py',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final nonce = List.generate(
        16,
        (i) => i + 16,
      ).map((b) => b.toRadixString(16).padLeft(2, '0')).join();
      final seen = <String>[];
      server.listen((request) async {
        final response = request.response;
        if (request.uri.path == '/challenge') {
          response.write(jsonEncode({'nonce': nonce}));
        } else {
          seen.add('${request.uri}|${request.headers.value('X-MotorPi-Auth')}');
          response.write(
            request.uri.path == '/logs'
                ? jsonEncode([
                    {
                      'name': 'watchdog',
                      'label': 'Watchdog',
                      'available': true,
                    },
                  ])
                : 'line 1\n',
          );
        }
        await response.close();
      });
      final client = LogClient(
        host: '127.0.0.1',
        port: server.port,
        key: List.generate(16, (i) => i),
      );
      expect((await client.sources()).single.name, 'watchdog');
      expect(await client.fetch('watchdog'), 'line 1\n');
      expect(seen.last, '/logs/watchdog?lines=200|$nonce:$golden');
      client.close();
      await server.close(force: true);
    },
  );

  test('a rejected request surfaces the Pi reason', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    server.listen((request) async {
      if (request.uri.path == '/challenge') {
        request.response.write(jsonEncode({'nonce': '00' * 16}));
      } else {
        request.response
          ..statusCode = 403
          ..write('Invalid access code');
      }
      await request.response.close();
    });
    final client = LogClient(
      host: '127.0.0.1',
      port: server.port,
      key: List.filled(16, 0),
    );
    await expectLater(
      client.sources(),
      throwsA(
        isA<HttpException>().having(
          (e) => e.message,
          'message',
          'Pi 403: Invalid access code',
        ),
      ),
    );
    client.close();
    await server.close(force: true);
  });
}
