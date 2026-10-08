import os
import struct
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

import app


def png_chunks(raw):
    offset = 8
    while offset < len(raw):
        size = struct.unpack('>I', raw[offset:offset + 4])[0]
        kind = raw[offset + 4:offset + 8]
        payload = raw[offset + 8:offset + 8 + size]
        yield kind, payload
        offset += size + 12


class StatusChartTests(unittest.TestCase):
    def test_png_has_300_dpi_and_print_size(self):
        counts = {'star': 1, 'preferred': 2, 'accepted': 3,
                  'neglected': 2, 'rejected': 1, 'isolated': 1}
        raw = app.render_status_chart_png(counts)
        self.assertTrue(raw.startswith(b'\x89PNG\r\n\x1a\n'))
        chunks = dict(png_chunks(raw))
        width, height = struct.unpack('>II', chunks[b'IHDR'][:8])
        x_ppm, y_ppm, unit = struct.unpack('>IIB', chunks[b'pHYs'])
        self.assertGreaterEqual(width, 2400)
        self.assertGreaterEqual(height, 1500)
        self.assertEqual(unit, 1)
        self.assertGreaterEqual(x_ppm, 11810)
        self.assertGreaterEqual(y_ppm, 11810)

    def test_empty_chart_is_still_a_valid_png(self):
        raw = app.render_status_chart_png({key: 0 for key in
                                           ('star', 'preferred', 'accepted', 'neglected', 'rejected', 'isolated')})
        self.assertTrue(raw.startswith(b'\x89PNG\r\n\x1a\n'))

    def test_endpoint_uses_local_study_categories(self):
        with tempfile.TemporaryDirectory() as temp:
            old_db = app.DB_PATH
            app.DB_PATH = os.path.join(temp, 'study.db')
            server = None
            try:
                app.init_db()
                with app.db() as conn:
                    sid = app.create_study(conn, {'name': 'Пример', 'members': ['А', 'Б', 'В']})
                    cid = app.get_study(conn, sid)['criteria'][0]['id']
                server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                url = 'http://127.0.0.1:%d/api/criteria/%d/status-chart.png' % (server.server_port, cid)
                with urllib.request.urlopen(url, timeout=10) as response:
                    self.assertEqual(response.headers.get_content_type(), 'image/png')
                    self.assertTrue(response.read().startswith(b'\x89PNG\r\n\x1a\n'))
            finally:
                if server:
                    server.shutdown()
                    server.server_close()
                app.DB_PATH = old_db


if __name__ == '__main__':
    unittest.main()
