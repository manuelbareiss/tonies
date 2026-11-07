"""GUI boundary tests; all writes are mocked or use the real dry-run path."""
import http.client
import json
import re
import socket
import threading
import time
import unittest
from unittest.mock import patch

from tonie_writer import catalog
from tonie_writer.gui import Handler, ToolboxServer, command_for
from tests.test_catalog import ENTRIES, ZUMA_EN


class CommandTests(unittest.TestCase):
    def command(self, **values):
        with patch('tonie_writer.gui.catalog.load_catalog', return_value=ENTRIES):
            return command_for({'action': 'preview', 'id': ZUMA_EN.id, **values})

    def test_exact_language_selection_and_preview(self):
        argv, stdin = self.command(port='/dev/ttyACM0', mode='blocks', retries=4)
        self.assertIn(ZUMA_EN.id, argv)
        self.assertEqual(argv[argv.index('--language') + 1], 'English')
        self.assertIn('--dry-run', argv)
        self.assertIn('--blocks-only', argv)
        self.assertNotIn('--yes', argv)
        self.assertEqual(stdin, '')

    def test_writes_and_probe_require_confirmation(self):
        for action in ('write', 'probe'):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.command(action=action)
        argv, _ = self.command(action='write', confirmed=True, mode='uid', no_verify=True)
        self.assertIn('--yes', argv)
        self.assertIn('--uid-only', argv)
        self.assertIn('--no-verify', argv)
        argv, stdin = self.command(action='probe', confirmed=True)
        self.assertEqual(argv[-2:], ['doctor', '--probe-magic'])
        self.assertEqual(stdin, 'y\n')

    def test_rejects_invalid_payloads_before_launch(self):
        for values in ({'action': 'shell'}, {'id': '../../etc/passwd'}, {'mode': 'unsafe'},
                       {'retries': 0}, {'retries': True}, {'retries': 11}, {'port': 42}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.command(**values)

    def test_all_non_write_tools(self):
        for action in ('read', 'doctor', 'index'):
            argv, stdin = self.command(action=action, verbose=True, json=True)
            self.assertEqual(argv[-1], action)
            self.assertIn('--verbose', argv)
            self.assertIn('--json', argv)
            self.assertEqual(stdin, '')


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ToolboxServer(('127.0.0.1', 0))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, payload=None, headers=None, method=None):
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=15)
        conn.request(method or ('POST' if payload is not None else 'GET'), path,
                     body=json.dumps(payload) if payload is not None else None,
                     headers=headers or {})
        response = conn.getresponse()
        status, data, response_headers = response.status, response.read(), dict(response.getheaders())
        conn.close()
        return status, data, response_headers

    def test_locales_are_served_and_cover_ui_keys(self):
        locales = {}
        for lang in ('en', 'de'):
            status, body, headers = self.request(f'/locale-{lang}.js')
            self.assertEqual(status, 200)
            self.assertTrue(headers['Content-Type'].startswith('text/javascript'))
            source = body.decode('utf-8')
            locales[lang] = json.loads(source.split(f'window.tonieLocales.{lang} = ', 1)[1].rstrip(';\n'))
        self.assertEqual(locales['en'].keys(), locales['de'].keys())
        _, html, _ = self.request('/')
        _, app, _ = self.request('/app.js')
        keys = set(re.findall(r'data-i18n(?:-placeholder|-aria-label)?="([^"]+)"', html.decode()))
        keys.update(re.findall(r"\bt\('([^']+)'", app.decode()))
        self.assertFalse(keys - locales['en'].keys(), keys - locales['en'].keys())
        for key in ('write_confirmation_description', 'verification_disabled', 'verification_enabled'):
            self.assertTrue(locales['de'][key])

    def test_catalog_details_search_and_download(self):
        status, body, _ = self.request('/api/catalog')
        entries = json.loads(body)['tonies']
        self.assertEqual(status, 200)
        self.assertEqual(len(entries), len(catalog.load_catalog()))
        entry = entries[0]
        status, body, _ = self.request('/api/entry?id=' + entry['id'])
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)['blocks']), 8)
        status, body, headers = self.request('/api/download?id=' + entry['id'])
        self.assertEqual(status, 200)
        self.assertIn(b'Filetype: Flipper NFC device', body)
        self.assertIn('attachment;', headers['Content-Disposition'])
        status, body, _ = self.request('/api/search?q=' + entry['uid'])
        self.assertIn(entry['id'], [e['id'] for e in json.loads(body)['tonies']])

    def test_protects_actions_and_limits_static_routes(self):
        status, _, _ = self.request('/api/run', {'action': 'read'})
        self.assertEqual(status, 403)
        headers = {'X-Toolbox-Token': self.server.token, 'Origin': 'https://untrusted.example'}
        status, _, _ = self.request('/api/run', {'action': 'read'}, headers)
        self.assertEqual(status, 403)
        status, _, _ = self.request('/api/config', headers={'Host': 'untrusted.example'})
        self.assertEqual(status, 403)
        status, _, _ = self.request('/../README.md')
        self.assertEqual(status, 404)
        status, _, _ = self.request('/api/entry?id=not-present')
        self.assertEqual(status, 404)
        with patch('tonie_writer.gui.subprocess.Popen') as proc:
            status, _, _ = self.request('/api/run', {'action': 'write', 'id': catalog.load_catalog()[0].id},
                                         {'X-Toolbox-Token': self.server.token})
            self.assertEqual(status, 400)
            proc.assert_not_called()

    def test_real_preview_job_without_hardware(self):
        entry = catalog.load_catalog()[0]
        headers = {'X-Toolbox-Token': self.server.token}
        status, body, _ = self.request('/api/run', {'action': 'preview', 'id': entry.id}, headers)
        self.assertEqual(status, 202)
        job_id = json.loads(body)['id']
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            _, body, _ = self.request('/api/jobs/' + job_id)
            job = json.loads(body)
            if job['done']:
                break
            time.sleep(.05)
        self.assertTrue(job['done'])
        self.assertEqual(job['code'], 0, job['output'])
        commands = job['output'].splitlines()
        self.assertEqual(len(commands), 10)
        self.assertIn('wrbl', commands[0])
        self.assertIn('02E00941', commands[8])
        self.assertIn('02E00940', commands[9])

    def test_serializes_operations(self):
        with self.server.job_lock:
            self.server.busy = True
        try:
            with self.assertRaises(RuntimeError):
                self.server.start_job({'action': 'read'})
        finally:
            with self.server.job_lock:
                self.server.busy = False

    def test_job_response_does_not_hold_lock(self):
        with self.server.job_lock:
            self.server.jobs['lock-test'] = {'id': 'lock-test', 'done': False}
        send_data = Handler.send_data
        lock_states = []
        def check_lock(handler, *args, **kwargs):
            lock_states.append(handler.server.job_lock.locked())
            return send_data(handler, *args, **kwargs)
        try:
            with patch.object(Handler, 'send_data', check_lock):
                status, body, _ = self.request('/api/jobs/lock-test')
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)['id'], 'lock-test')
            self.assertEqual(lock_states, [False])
        finally:
            with self.server.job_lock:
                del self.server.jobs['lock-test']

    def test_stalled_request_body_times_out(self):
        with patch.object(Handler, 'timeout', 0.1), socket.create_connection(self.server.server_address, timeout=2) as conn:
            conn.sendall((f'POST /api/run HTTP/1.1\r\nHost: 127.0.0.1:{self.server.server_port}\r\n'
                          f'X-Toolbox-Token: {self.server.token}\r\nContent-Length: 10\r\n\r\n{{').encode())
            self.assertIn(b' 408 ', conn.recv(1024))

    def test_frontend_assets_are_served(self):
        for path, content_type in (('/', 'text/html'), ('/app.js', 'text/javascript'),
                                   ('/theme.js', 'text/javascript'), ('/style.css', 'text/css')):
            status, body, headers = self.request(path)
            self.assertEqual(status, 200)
            self.assertGreater(len(body), 100)
            self.assertTrue(headers['Content-Type'].startswith(content_type))
            self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])

    def test_head_probe_matches_get_headers_without_a_body(self):
        for path in ('/', '/style.css', '/theme.js', '/api/catalog', '/missing'):
            with self.subTest(path=path):
                status, body, headers = self.request(path)
                head_status, head_body, head_headers = self.request(path, method='HEAD')
                self.assertEqual(head_status, status)
                self.assertEqual(head_body, b'')
                self.assertEqual(int(head_headers['Content-Length']), len(body))
                self.assertEqual(head_headers['Content-Type'], headers['Content-Type'])


if __name__ == '__main__':
    unittest.main()
