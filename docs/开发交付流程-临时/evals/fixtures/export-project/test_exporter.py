import unittest

from exporter import export_csv


class ExportTests(unittest.TestCase):
    def test_nonempty_format(self):
        self.assertEqual(export_csv([{"id": 1, "name": "张三"}]), "id,name\r\n1,张三\r\n")

    def test_permission(self):
        with self.assertRaises(PermissionError):
            export_csv([], can_export=False)


if __name__ == "__main__":
    unittest.main()
