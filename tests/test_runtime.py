import os
import json
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import threading
import unittest
import urllib.request
from contextlib import closing
from unittest.mock import patch

import app


class RuntimePathsTests(unittest.TestCase):
    def test_api_acknowledges_changes_only_after_database_commit(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(app, 'DB_PATH', os.path.join(temp, 'commit.db')):
            app.init_db()
            visible_counts = []

            class ObservingHandler(app.Handler):
                def send_response(self, status, message=None):
                    if status == 200:
                        with closing(sqlite3.connect(app.DB_PATH)) as observer:
                            visible_counts.append(observer.execute('SELECT COUNT(*) FROM studies').fetchone()[0])
                    super().send_response(status, message)

            server = app.ThreadingHTTPServer(('127.0.0.1', 0), ObservingHandler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                request = urllib.request.Request('http://127.0.0.1:%d/api/studies' % server.server_port,
                    data=json.dumps({'name': 'Durable acknowledgement', 'members': ['Alpha']}).encode(),
                    headers={'Content-Type': 'application/json'}, method='POST')
                with urllib.request.urlopen(request, timeout=3) as response:
                    self.assertGreater(json.load(response)['id'], 0)
                self.assertEqual(visible_counts, [1], 'Success response was sent before the data committed')
            finally:
                server.shutdown()
                server.server_close()

    def test_desktop_ready_url_and_data_survive_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            ready = os.path.join(temp, 'ready.json')
            env = dict(os.environ, SOCIOMETRY_DB=os.path.join(temp, 'desktop.db'),
                       SOCIOMETRY_PORT='0', SOCIOMETRY_READY_FILE=ready)
            for launch in range(2):
                if os.path.exists(ready):
                    os.unlink(ready)
                env.pop('PYTHONUNBUFFERED', None)
                log_path = os.path.join(temp, 'server.log')
                with open(log_path, 'wb') as output:
                    proc = subprocess.Popen([sys.executable, os.path.abspath(app.__file__), '--no-browser'],
                                            env=env, stdout=output, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 45
                    while not os.path.isfile(ready) and time.monotonic() < deadline:
                        if proc.poll() is not None:
                            self.fail('Desktop server exited: ' + proc.stderr.read().decode(errors='replace'))
                        time.sleep(0.05)
                    self.assertTrue(os.path.isfile(ready), 'Desktop did not receive its startup URL')
                    with open(ready) as file:
                        runtime = json.load(file)
                    self.assertEqual(runtime['pid'], proc.pid)
                    self.assertRegex(runtime['url'], r'^http://127\.0\.0\.1:[1-9][0-9]*/$')
                    with open(log_path, 'rb') as output:
                        self.assertIn(runtime['url'].encode('ascii'), output.read(), 'Desktop startup log is buffered')
                    with urllib.request.urlopen(runtime['url'] + 'api/studies', timeout=3) as response:
                        studies = json.load(response)
                    if launch == 0:
                        self.assertEqual(studies, [])
                        request = urllib.request.Request(runtime['url'] + 'api/studies',
                            data=json.dumps({'name': 'Desktop persistence', 'members': ['Alpha', 'Beta']}).encode(),
                            headers={'Content-Type': 'application/json'}, method='POST')
                        with urllib.request.urlopen(request, timeout=3) as response:
                            self.assertGreater(json.load(response)['id'], 0)
                    else:
                        self.assertEqual([study['name'] for study in studies], ['Desktop persistence'])
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                    proc.communicate(timeout=5)

    def test_desktop_server_exits_when_its_parent_is_gone(self):
        with tempfile.TemporaryDirectory() as temp:
            ready = os.path.join(temp, 'ready.json')
            env = dict(os.environ, SOCIOMETRY_DB=os.path.join(temp, 'desktop.db'),
                       SOCIOMETRY_PORT='0', SOCIOMETRY_PARENT_PID='0', SOCIOMETRY_READY_FILE=ready)
            proc = subprocess.Popen([sys.executable, os.path.abspath(app.__file__), '--no-browser'],
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 45
                while not os.path.isfile(ready) and proc.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(os.path.isfile(ready), 'Desktop server never completed startup')
                deadline = time.monotonic() + 5
                while proc.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertEqual(proc.poll(), 0, 'Orphaned desktop server is still running')
            finally:
                if proc.poll() is None:
                    proc.terminate()
                proc.communicate(timeout=5)

    def test_frozen_bundle_reads_resources_inside_and_writes_data_beside_executable(self):
        executable = os.path.abspath(os.path.join(os.path.sep, 'bundle', 'OpenSociometry', 'OpenSociometry'))
        resources = os.path.abspath(os.path.join(os.path.sep, 'bundle', 'OpenSociometry', '_internal'))
        with patch.object(app.sys, 'frozen', True, create=True), \
             patch.object(app.sys, '_MEIPASS', resources, create=True), \
             patch.object(app.sys, 'executable', executable):
            base, static = app.app_paths()
        self.assertEqual(base, os.path.dirname(executable))
        self.assertEqual(static, resources)

    def test_local_server_starts_with_ascii_console(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        with tempfile.TemporaryDirectory() as temp:
            env = os.environ.copy()
            env['SOCIOMETRY_DB'] = os.path.join(temp, 'study.db')
            env['SOCIOMETRY_PORT'] = str(port)
            env['PYTHONIOENCODING'] = 'ascii'
            proc = subprocess.Popen([sys.executable, os.path.abspath(app.__file__), '--no-browser'],
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                for _ in range(100):
                    try:
                        with urllib.request.urlopen('http://127.0.0.1:%d/api/studies' % port,
                                                    timeout=0.5) as response:
                            self.assertEqual(json.load(response), [])
                            break
                    except Exception:
                        if proc.poll() is not None:
                            self.fail('Server exited with ASCII console')
                        time.sleep(0.1)
                else:
                    self.fail('Server did not start with ASCII console')
            finally:
                if proc.poll() is None:
                    proc.terminate()
                proc.communicate(timeout=5)

    def test_occupied_port_binds_current_app_to_a_free_port(self):
        while True:
            occupied = socket.socket()
            occupied.bind(('127.0.0.1', 0))
            port = occupied.getsockname()[1]
            try:
                with socket.socket() as next_port:
                    next_port.bind(('127.0.0.1', port + 1))
                adjacent_is_free = True
            except OSError:
                adjacent_is_free = False
            if port < 65000 and adjacent_is_free:
                break
            occupied.close()
        try:
            occupied.listen()
            server = app.bind_server(port)
            try:
                self.assertGreater(server.server_port, port)
                self.assertLess(server.server_port, port + 20)
            finally:
                server.server_close()
        finally:
            occupied.close()

    def test_reserved_windows_port_is_skipped(self):
        denied = PermissionError(13, 'Port reserved')
        denied.winerror = 10013
        next_server = object()
        with patch.object(app, 'ThreadingHTTPServer', side_effect=[denied, next_server]) as factory:
            self.assertIs(app.bind_server(8765), next_server)
        self.assertEqual(factory.call_count, 2)


if __name__ == '__main__':
    unittest.main()
