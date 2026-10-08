import os
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from unittest.mock import patch

import app


class RuntimePathsTests(unittest.TestCase):
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

    def test_occupied_port_starts_current_app_on_next_port(self):
        while True:
            occupied = socket.socket()
            occupied.bind(('127.0.0.1', 0))
            port = occupied.getsockname()[1]
            if port < 65000:
                break
            occupied.close()
        try:
            occupied.listen()
            with tempfile.TemporaryDirectory() as temp:
                env = os.environ.copy()
                env['SOCIOMETRY_DB'] = os.path.join(temp, 'study.db')
                env['SOCIOMETRY_PORT'] = str(port)
                proc = subprocess.Popen([sys.executable, os.path.abspath(app.__file__), '--no-browser'],
                                        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                try:
                    for _ in range(60):
                        try:
                            with urllib.request.urlopen('http://127.0.0.1:%d/api/studies' % (port + 1),
                                                        timeout=0.2) as response:
                                self.assertEqual(json.load(response), [])
                                self.assertTrue(response.headers['Server'].startswith('OpenSociometry/'))
                                break
                        except Exception:
                            if proc.poll() is not None:
                                self.fail('Current app exited instead of selecting the next port')
                            time.sleep(0.1)
                    else:
                        self.fail('Current app did not start on the next port')
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                    proc.communicate(timeout=5)
        finally:
            occupied.close()


if __name__ == '__main__':
    unittest.main()
