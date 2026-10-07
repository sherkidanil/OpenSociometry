import base64
import os
import tempfile
import unittest

import app


PNG_1X1 = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='
)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = app.DB_PATH
        app.DB_PATH = os.path.join(self.tmp.name, 'study.db')
        app.init_db()
        with app.db() as conn:
            self.sid = app.create_study(conn, {'name': 'Тест', 'members': ['Анна', 'Борис']})
            study = app.get_study(conn, self.sid)
            self.cid = study['criteria'][0]['id']
            self.a, self.b = [m['id'] for m in study['members']]

    def tearDown(self):
        app.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_photo_stays_local_and_round_trips_in_backup(self):
        with app.db() as conn:
            app.set_member_photo(conn, self.a, PNG_1X1)
            self.assertTrue(app.get_study(conn, self.sid)['members'][0]['has_photo'])
            self.assertEqual(app.get_member_photo(conn, self.a), ('image/png', PNG_1X1))
            data = app.export_study(conn, self.sid)
            self.assertEqual(data['format'], 'opensociometry/3')
            restored = app.import_study_json(conn, data)
            new_a = app.get_study(conn, restored)['members'][0]['id']
            self.assertEqual(app.get_member_photo(conn, new_a), ('image/png', PNG_1X1))

    def test_rejects_non_image_as_photo(self):
        with app.db() as conn:
            with self.assertRaisesRegex(app.ApiError, 'изображен'):
                app.set_member_photo(conn, self.a, b'not an image')

    def test_graph_layout_survives_reopen_and_copy(self):
        with app.db() as conn:
            app.save_graph_layout(conn, self.cid, 'force', {str(self.a): [12, 33], str(self.b): [-8, 2]})
        with app.db() as conn:
            layout = app.get_graph_layout(conn, self.cid, 'force')
            self.assertEqual(layout[str(self.a)], [12, 33])
            copied = app.clone_study(conn, self.sid)
            copied_study = app.get_study(conn, copied)
            copied_cid = copied_study['criteria'][0]['id']
            copied_a = copied_study['members'][0]['id']
            self.assertEqual(app.get_graph_layout(conn, copied_cid, 'force')[str(copied_a)], [12, 33])

    def test_layout_rejects_other_study_member(self):
        with app.db() as conn:
            other = app.create_study(conn, {'name': 'Другая', 'members': ['Вера']})
            other_member = app.get_study(conn, other)['members'][0]['id']
            with self.assertRaises(app.ApiError):
                app.save_graph_layout(conn, self.cid, 'force', {str(other_member): [0, 0]})

    def test_invalid_backup_does_not_create_partial_study(self):
        with app.db() as conn:
            backup = app.export_study(conn, self.sid)
            backup['choices'] = [[0, 0, 99, 'pos']]
            with self.assertRaises(app.ApiError):
                app.import_study_json(conn, backup)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM studies').fetchone()[0], 1)

    def test_invalid_photo_encoding_rejected_as_bad_backup(self):
        with app.db() as conn:
            backup = app.export_study(conn, self.sid)
            backup['photos'] = [[0, 'image/png', 'not base64']]
            with self.assertRaises(app.ApiError):
                app.import_study_json(conn, backup)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM studies').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
