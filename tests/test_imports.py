import csv
import io
import os
import tempfile
import unittest
import zipfile

import app


def workbook(rows):
    """A small real OOXML workbook, without a test runtime dependency."""
    from xml.sax.saxutils import escape

    cells = []
    for row_number, row in enumerate(rows, 1):
        xml_cells = []
        for column, value in enumerate(row):
            ref = chr(65 + column) + str(row_number)
            xml_cells.append(
                '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>'
                % (ref, escape(str(value)))
            )
        cells.append('<row r="%d">%s</row>' % (row_number, ''.join(xml_cells)))
    xml = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>' % ''.join(cells)
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        z.writestr('xl/worksheets/sheet1.xml', xml)
    return out.getvalue()


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db = app.DB_PATH
        app.DB_PATH = os.path.join(self.tmp.name, 'study.db')
        app.init_db()
        with app.db() as conn:
            self.sid = app.create_study(conn, {'name': 'Тест'})
            self.cid = app.get_study(conn, self.sid)['criteria'][0]['id']

    def tearDown(self):
        app.DB_PATH = self.old_db
        self.tmp.cleanup()

    def test_numbered_participant_csv_imports_names_only(self):
        raw = '№;ФИО\n1;Анна\n2;Борис\n'.encode('utf-8')
        with app.db() as conn:
            result = app.import_file(conn, self.sid, None, 'people.csv', raw)
            self.assertEqual(result, {'mode': 'members', 'added': 2})
            self.assertEqual([m['name'] for m in app.get_study(conn, self.sid)['members']], ['Анна', 'Борис'])

    def test_matrix_xlsx_imports_signed_choices(self):
        raw = workbook([['', 'Анна', 'Борис'], ['Анна', '', '+'], ['Борис', '-', '']])
        with app.db() as conn:
            result = app.import_file(conn, self.sid, self.cid, 'choices.xlsx', raw)
            self.assertEqual((result['mode'], result['added'], result['choices']), ('matrix', 2, 2))
            study = app.get_study(conn, self.sid)
            self.assertEqual({c['kind'] for c in study['choices']}, {'pos', 'neg'})
            self.assertEqual(len(study['filled']), 2)

    def test_site_numbered_matrix_xlsx_imports_signed_choices(self):
        raw = workbook([['№', 'ФИО', 1, 2], [1, 'Анна', '', '+'],
                        [2, 'Борис', '-', '']])
        with app.db() as conn:
            result = app.import_file(conn, self.sid, self.cid, 'site.xlsx', raw, mode='matrix')
            study = app.get_study(conn, self.sid)
            self.assertEqual(result['choices'], 2)
            self.assertEqual([m['name'] for m in study['members']], ['Анна', 'Борис'])
            self.assertEqual({c['kind'] for c in study['choices']}, {'pos', 'neg'})

    def test_invalid_matrix_is_atomic(self):
        raw = 'Name,Анна,Борис\nАнна,,?\nБорис,+,\n'.encode()
        with self.assertRaises(app.ApiError):
            with app.db() as conn:
                app.import_file(conn, self.sid, self.cid, 'bad.csv', raw, mode='matrix')
        with app.db() as conn:
            study = app.get_study(conn, self.sid)
            self.assertEqual(study['members'], [])
            self.assertEqual(study['choices'], [])

    def test_duplicate_matrix_names_are_rejected(self):
        raw = 'Name,Анна,Анна\nАнна,,+\n'.encode()
        with self.assertRaisesRegex(app.ApiError, 'повтор'):
            with app.db() as conn:
                app.import_file(conn, self.sid, self.cid, 'duplicate.csv', raw, mode='matrix')

    def test_unsupported_extension_is_rejected(self):
        with self.assertRaisesRegex(app.ApiError, 'формат'):
            app.read_table('people.exe', 'Анна'.encode())

    def test_legacy_xls_import(self):
        fixture = os.path.join(os.path.dirname(__file__), 'fixtures', 'participants.xls')
        with open(fixture, 'rb') as f:
            table = app.read_table('participants.xls', f.read())
        self.assertEqual(table[:3], [['ФИО'], ['Анна'], ['Борис']])

    def test_prefilled_file_can_create_protocol_in_one_transaction(self):
        raw = workbook([['ФИО', 'Анна', 'Борис'], ['Анна', '', '+'], ['Борис', '-', '']])
        with app.db() as conn:
            result = app.create_study_from_file(conn, {'name': 'Группа'}, 'votes.xlsx', raw, 'matrix')
            study = app.get_study(conn, result['id'])
            self.assertEqual(study['name'], 'Группа')
            self.assertEqual(len(study['members']), 2)
            self.assertEqual(len(study['choices']), 2)

    def test_failed_file_does_not_leave_empty_protocol(self):
        with self.assertRaises(app.ApiError):
            with app.db() as conn:
                app.create_study_from_file(conn, {'name': 'Broken'}, 'votes.csv', b'bad', 'matrix')
        with app.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM studies").fetchone()[0], 1)

    def test_downloadable_templates_are_readable(self):
        base = os.path.join(os.path.dirname(__file__), '..', 'static', 'templates')
        for name, count in [('participants.xlsx', 1), ('choices.xlsx', 5)]:
            with self.subTest(name=name), open(os.path.join(base, name), 'rb') as f:
                table = app.read_table(name, f.read())
                self.assertGreaterEqual(len(table), 3)
                self.assertEqual(len(table[0]), count)


if __name__ == '__main__':
    unittest.main()
