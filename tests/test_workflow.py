import os
import tempfile
import unittest
import sqlite3

import app


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = app.DB_PATH
        app.DB_PATH = os.path.join(self.tmp.name, 'study.db')
        app.init_db()
        with app.db() as conn:
            self.sid = app.create_study(conn, {'name': 'Группа', 'members': ['Анна', 'Борис']})
            study = app.get_study(conn, self.sid)
            self.cid = study['criteria'][0]['id']
            self.anna, self.boris = [m['id'] for m in study['members']]

    def tearDown(self):
        app.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_filled_state_survives_database_reopen(self):
        with app.db() as conn:
            app.set_questionnaire_filled(conn, self.cid, self.anna, True)
        with app.db() as conn:
            self.assertEqual(app.get_study(conn, self.sid)['filled'],
                             [{'criterion_id': self.cid, 'member_id': self.anna}])
            app.set_questionnaire_filled(conn, self.cid, self.anna, False)
        with app.db() as conn:
            self.assertEqual(app.get_study(conn, self.sid)['filled'], [])

    def test_copy_study_keeps_choices_and_filled_state(self):
        with app.db() as conn:
            app.set_choice(conn, dict(criterion_id=self.cid, from_id=self.anna,
                                      to_id=self.boris, kind='pos'))
            app.set_questionnaire_filled(conn, self.cid, self.anna, True)
            copied_id = app.clone_study(conn, self.sid)
            copy = app.get_study(conn, copied_id)
            self.assertEqual(copy['name'], 'Группа (копия)')
            self.assertEqual(len(copy['members']), 2)
            self.assertEqual(len(copy['choices']), 1)
            self.assertEqual(len(copy['filled']), 1)
            self.assertNotEqual(copy['members'][0]['id'], self.anna)

    def test_backup_round_trip_keeps_filled_state(self):
        with app.db() as conn:
            app.set_questionnaire_filled(conn, self.cid, self.anna, True)
            data = app.export_study(conn, self.sid)
            self.assertEqual(data['format'], 'opensociometry/3')
            restored_id = app.import_study_json(conn, data)
            restored = app.get_study(conn, restored_id)
            self.assertEqual(len(restored['filled']), 1)

    def test_questionnaire_must_belong_to_criterion_study(self):
        with app.db() as conn:
            other = app.create_study(conn, {'name': 'Другие', 'members': ['Петр']})
            other_member = app.get_study(conn, other)['members'][0]['id']
            with self.assertRaises(app.ApiError):
                app.set_questionnaire_filled(conn, self.cid, other_member, True)

    def test_existing_database_gets_optimistic_setting_without_losing_study(self):
        old_db = os.path.join(self.tmp.name, 'old.db')
        with sqlite3.connect(old_db) as conn:
            conn.execute("CREATE TABLE studies (id INTEGER PRIMARY KEY, name TEXT, description TEXT, max_pos INTEGER, max_neg INTEGER, perceptual INTEGER, created_at TEXT, updated_at TEXT)")
            conn.execute("INSERT INTO studies VALUES (1,'Старая группа','',0,0,0,'now','now')")
        app.DB_PATH = old_db
        app.init_db()
        with app.db() as conn:
            self.assertEqual(app.get_study(conn, 1)['optimistic'], 0)
            self.assertEqual(app.get_study(conn, 1)['name'], 'Старая группа')


if __name__ == '__main__':
    unittest.main()
