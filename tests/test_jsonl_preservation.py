"""Malformed JSONL lines and the original file must survive edits and failed saves."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Utils'))
import jsonl_store


class JsonlPreservationTests(unittest.TestCase):
    def test_malformed_non_object_and_invalid_utf8_lines_survive_repeated_saves(self):
        broken = [b'{"id":\r\n', b'[1, 2]\n', b'\xffbroken\r\n']
        original = (b'{"id": "1", "status": "old"}\r\n' + b''.join(broken)
                    + b'\r\n{"id": "2", "status": "old"}')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'links.jsonl'
            path.write_bytes(original)
            records = jsonl_store.load_records(path)
            self.assertEqual([record['id'] for record in records], ['1', '2'])
            self.assertEqual(records.invalid_lines, [2, 3, 4])
            records.append({'id': '3', 'note': '新增链接'})
            for status in ('edited', 'edited again'):
                records[0]['status'] = status
                backup = jsonl_store.save_records(path, records)
                self.assertEqual(backup.read_bytes(), original)
                saved = path.read_bytes()
                for raw in broken:
                    self.assertEqual(saved.count(raw), 1)
                restored = jsonl_store.load_records(path)
                self.assertEqual(len(restored), 3)
                self.assertEqual(restored[0]['status'], status)
                self.assertEqual(restored[2]['note'], '新增链接')
            self.assertEqual(len(list(Path(folder).glob('*.bak*'))), 1)

    def test_new_records_do_not_merge_into_an_unterminated_damaged_final_line(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'links.jsonl'
            path.write_bytes(b'{broken final line')
            records = jsonl_store.load_records(path)
            records.append({'id': 'new'})
            jsonl_store.save_records(path, records)
            lines = path.read_bytes().splitlines()
            self.assertEqual(lines[0], b'{broken final line')
            self.assertEqual(json.loads(lines[1]), {'id': 'new'})

    def test_existing_backups_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'links.jsonl'
            path.write_bytes(b'{broken}\n')
            old_backup = path.with_name('links.jsonl.bak')
            old_backup.write_bytes(b'older backup')
            records = jsonl_store.load_records(path)
            backup = jsonl_store.save_records(path, records)
            self.assertEqual(backup.name, 'links.jsonl.bak2')
            self.assertEqual(backup.read_bytes(), b'{broken}\n')
            self.assertEqual(old_backup.read_bytes(), b'older backup')

    def test_temporary_write_or_replace_failure_keeps_the_original_and_cleans_temporary_files(self):
        for failing_call in ('fsync', 'replace'):
            with self.subTest(failing_call=failing_call), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'links.jsonl'
                original = b'{"id": "1", "status": "old"}\n'
                path.write_bytes(original)
                records = jsonl_store.load_records(path)
                records[0]['status'] = 'new'
                with patch.object(jsonl_store.os, failing_call, side_effect=OSError('disk error')):
                    with self.assertRaisesRegex(OSError, 'disk error'):
                        jsonl_store.save_records(path, records)
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(list(Path(folder).iterdir()), [path])
                # A failed save must not prevent a later retry using the same records.
                jsonl_store.save_records(path, records)
                self.assertEqual(jsonl_store.load_records(path)[0]['status'], 'new')

    def test_serialization_error_does_not_truncate_the_source(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'links.jsonl'
            original = b'{"id": "1"}\n'
            path.write_bytes(original)
            records = jsonl_store.load_records(path)
            records[0]['invalid'] = object()
            with self.assertRaises(TypeError):
                jsonl_store.save_records(path, records)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_backup_failure_keeps_the_damaged_source(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'links.jsonl'
            path.write_bytes(b'{broken}\n')
            records = jsonl_store.load_records(path)
            with patch.object(jsonl_store, '_backup_source', side_effect=OSError('backup error')):
                with self.assertRaisesRegex(OSError, 'backup error'):
                    jsonl_store.save_records(path, records)
            self.assertEqual(path.read_bytes(), b'{broken}\n')

    def test_external_edits_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'links.jsonl'
            path.write_bytes(b'{"id": "1"}\n')
            records = jsonl_store.load_records(path)
            external = b'{"id": "1"}\n{"id": "external"}\n'
            path.write_bytes(external)
            records[0]['status'] = 'new'
            with self.assertRaises(RuntimeError):
                jsonl_store.save_records(path, records)
            self.assertEqual(path.read_bytes(), external)

    def test_new_and_bom_encoded_files_remain_editable(self):
        for original in (None, b'\xef\xbb\xbf{"id": "1"}\r\n\r\n'):
            with self.subTest(original=original), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'links.jsonl'
                if original is not None:
                    path.write_bytes(original)
                records = jsonl_store.load_records(path)
                self.assertEqual(records.invalid_lines, [])
                records.append({'id': 'new'})
                self.assertIsNone(jsonl_store.save_records(path, records))
                self.assertEqual(jsonl_store.load_records(path)[-1]['id'], 'new')

    def test_gui_reports_a_failed_save_without_modifying_the_source(self):
        spec = importlib.util.spec_from_file_location('jsonl_gui_test', ROOT / 'Utils' / 'Assembly line' / 'jsonl_gui.py')
        gui = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gui)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'links.jsonl'
            path.write_bytes(b'{"id": "1"}\n')
            with patch.object(gui, 'JSONL_PATH', path):
                records = gui.load_records()
                app = SimpleNamespace(records=records, root=object())
                records[0]['status'] = 'edited'
                with patch.object(jsonl_store.os, 'replace', side_effect=OSError('write failed')), \
                     patch.object(gui.messagebox, 'showerror') as showerror:
                    self.assertFalse(gui.LinkBrowserApp.save_all(app))
                    showerror.assert_called_once()
                    self.assertIn('write failed', showerror.call_args.args[1])
                self.assertEqual(path.read_bytes(), b'{"id": "1"}\n')
                self.assertTrue(gui.LinkBrowserApp.save_all(app))
                self.assertEqual(jsonl_store.load_records(path)[0]['status'], 'edited')


if __name__ == '__main__':
    unittest.main()
