import os
import tempfile
import unittest

import app


class ResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = app.DB_PATH
        app.DB_PATH = os.path.join(self.tmp.name, 'study.db')
        app.init_db()
        with app.db() as conn:
            self.sid = app.create_study(conn, {'name': 'Тест', 'members': ['А', 'Б', 'В']})
            study = app.get_study(conn, self.sid)
            self.cid = study['criteria'][0]['id']
            self.a, self.b, self.c = [m['id'] for m in study['members']]

    def tearDown(self):
        app.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_report_pairs_and_site_group_indices(self):
        with app.db() as conn:
            for source, target, kind in [
                (self.a, self.b, 'pos'), (self.b, self.a, 'pos'),
                (self.a, self.c, 'pos'), (self.c, self.a, 'neg')]:
                app.set_choice(conn, dict(criterion_id=self.cid, from_id=source,
                                          to_id=target, kind=kind))
            report = app.compute(conn, self.cid)
        self.assertEqual(len(report['pairs']['mutual_pos']), 1)
        self.assertEqual(len(report['pairs']['paradoxical']), 1)
        self.assertEqual(report['group']['expansiveness_total'], 1.333)
        self.assertEqual(report['group']['reference'], 0.333)
        self.assertEqual(report['group']['cohesion'], 0.333)
        people = {m['name']: m for m in report['members']}
        self.assertEqual(people['А']['satisfaction'], 0.5)

    def test_published_status_groups_and_optimistic_option(self):
        self.assertEqual(app.classify_status(0, 0, 4, 2), 'isolated')
        self.assertEqual(app.classify_status(9, 1, 4, 2), 'star')
        self.assertEqual(app.classify_status(6, 2, 4, 2), 'preferred')
        self.assertEqual(app.classify_status(1, 8, 4, 2), 'rejected')
        self.assertEqual(app.classify_status(1, 2, 4, 2), 'neglected')
        self.assertEqual(app.classify_status(1, 2, 4, 2, optimistic=True), 'neglected')
        self.assertEqual(app.classify_status(1, 1, 4, 2), 'accepted')
        self.assertEqual(app.classify_status(3, 0, 4, 2, optimistic=True), 'accepted')

    def test_no_choices_gives_zero_group_rates(self):
        with app.db() as conn:
            report = app.compute(conn, self.cid)
        self.assertEqual(report['group']['expansiveness_total'], 0)
        self.assertEqual(report['group']['reference'], 0)
        self.assertEqual(report['group']['cohesion'], 0)
        self.assertEqual(report['group']['categories']['isolated'], 3)


if __name__ == '__main__':
    unittest.main()
