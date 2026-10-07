import os
import unittest
from unittest.mock import patch

import app


class RuntimePathsTests(unittest.TestCase):
    def test_frozen_bundle_reads_resources_inside_and_writes_data_beside_executable(self):
        executable = os.path.join(os.path.sep, 'bundle', 'OpenSociometry', 'OpenSociometry')
        resources = os.path.join(os.path.sep, 'bundle', 'OpenSociometry', '_internal')
        with patch.object(app.sys, 'frozen', True, create=True), \
             patch.object(app.sys, '_MEIPASS', resources, create=True), \
             patch.object(app.sys, 'executable', executable):
            base, static = app.app_paths()
        self.assertEqual(base, os.path.dirname(executable))
        self.assertEqual(static, resources)


if __name__ == '__main__':
    unittest.main()
