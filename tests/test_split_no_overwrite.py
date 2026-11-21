"""Protect existing split files and keep each CSV/JSON pair on the same stem."""
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'Json Crawler system'
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / 'Utils'))
from common.step_loader import alias_step
from switch_tool.features.split_by_title import (
    save_split_workbook, split_by_title as utility_split_parts,
)
from switch_tool.features.split_by_title_each import split_by_title_each as utility_split_each


class SplitNoOverwriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stage = APP / 'stages' / '03_1_split'
        alias_step('config', stage / '00_config.py')
        cls.splitter = alias_step('splitter', stage / '20_split.py')

    def source(self, folder):
        path = Path(folder) / 'sample_style.csv'
        self.write_source(path, 'initial')
        return path

    def write_source(self, path, value):
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['title', 'price1', 'md5', 'name'])
            writer.writerow(['Tops', '20', 'product-a', value])

    def split(self, mode, source, overwrite=False):
        if mode == 'parts':
            return self.splitter.split_by_title(source, 1, overwrite=overwrite, log=lambda *_: None)
        return self.splitter.split_by_title_each(source, overwrite=overwrite, log=lambda *_: None)

    def sync_json(self, stat, value, overwrite=False):
        return self.splitter.split_json_by_md5(
            [{'md5': 'product-a', 'value': value}], stat['md5_sets'],
            json_targets=stat['json_targets'], overwrite=overwrite, log=lambda *_: None,
        )[0][0]

    def test_four_runs_preserve_all_previous_csv_and_json_contents(self):
        for mode in ('parts', 'each'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                source = self.source(folder)
                saved = {}
                base = 'sample_style_1' if mode == 'parts' else 'Tops'
                for run, suffix in enumerate(('', '_新', '_新2', '_新3'), 1):
                    self.write_source(source, str(run))
                    stat = self.split(mode, source)
                    csv_path = stat['outputs'][0]
                    json_path = self.sync_json(stat, run)
                    self.assertEqual(csv_path.stem, base + suffix)
                    self.assertEqual(csv_path.stem, json_path.stem)
                    for path, content in saved.items():
                        self.assertEqual(path.read_bytes(), content)
                    self.assertNotIn(csv_path, saved)
                    self.assertNotIn(json_path, saved)
                    saved[csv_path] = csv_path.read_bytes()
                    saved[json_path] = json_path.read_bytes()

    def test_csv_only_or_json_only_collision_advances_both_names(self):
        for mode in ('parts', 'each'):
            for existing in ('csv', 'json'):
                with self.subTest(mode=mode, existing=existing), tempfile.TemporaryDirectory() as folder:
                    source = self.source(folder)
                    stat = self.split(mode, source)
                    csv_path = stat['outputs'][0]
                    json_path = Path(stat['json_targets'][str(csv_path)])
                    if existing == 'json':
                        csv_path.unlink()
                        json_path.write_text('original json', encoding='utf-8')
                    kept = csv_path if existing == 'csv' else json_path
                    original = kept.read_bytes()
                    stat = self.split(mode, source)
                    next_csv = stat['outputs'][0]
                    next_json = self.sync_json(stat, 'next')
                    self.assertEqual(next_csv.stem, csv_path.stem + '_新')
                    self.assertEqual(next_csv.stem, next_json.stem)
                    self.assertEqual(kept.read_bytes(), original)

    def test_mixed_existing_suffixes_are_skipped_as_pairs(self):
        for mode in ('parts', 'each'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                source = self.source(folder)
                stat = self.split(mode, source)
                csv_path = stat['outputs'][0]
                json_path = Path(stat['json_targets'][str(csv_path)])
                occupied = [csv_path, json_path.with_stem(json_path.stem + '_新'),
                            csv_path.with_stem(csv_path.stem + '_新2')]
                for path in occupied:
                    path.write_text('keep this file', encoding='utf-8')
                stat = self.split(mode, source)
                next_csv = stat['outputs'][0]
                next_json = self.sync_json(stat, 'next')
                self.assertEqual(next_csv.stem, csv_path.stem + '_新3')
                self.assertEqual(next_csv.stem, next_json.stem)
                for path in occupied:
                    self.assertEqual(path.read_text(encoding='utf-8'), 'keep this file')

    def test_overwrite_enabled_replaces_the_original_pair(self):
        for mode in ('parts', 'each'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                source = self.source(folder)
                old = self.split(mode, source)
                self.sync_json(old, 'old')
                old_csv = old['outputs'][0]
                self.write_source(source, 'new')
                new = self.split(mode, source, overwrite=True)
                new_json = self.sync_json(new, 'new', overwrite=True)
                self.assertEqual(new['outputs'], old['outputs'])
                self.assertIn('new', old_csv.read_text(encoding='utf-8'))
                self.assertEqual(json.loads(new_json.read_text(encoding='utf-8'))[0]['value'], 'new')

    def test_json_created_after_csv_is_preserved_and_pair_is_not_renamed(self):
        with tempfile.TemporaryDirectory() as folder:
            source = self.source(folder)
            stat = self.split('parts', source)
            csv_path = stat['outputs'][0]
            target = Path(stat['json_targets'][str(csv_path)])
            target.write_text('created by another writer', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                self.sync_json(stat, 'new')
            self.assertEqual(target.read_text(encoding='utf-8'), 'created by another writer')
            self.assertFalse(target.with_stem(target.stem + '_新').exists())

    def test_standalone_json_writes_find_the_next_available_name(self):
        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / 'part.csv'
            saved = {}
            for run, suffix in enumerate(('', '_新', '_新2', '_新3')):
                path, count = self.splitter.split_json_by_md5(
                    [{'md5': 'product-a', 'value': run}], {str(csv_path): {'product-a'}},
                    overwrite=False, log=lambda *_: None,
                )[0]
                self.assertEqual(path.stem, 'part' + suffix)
                self.assertEqual(count, 1)
                for old, content in saved.items():
                    self.assertEqual(old.read_bytes(), content)
                saved[path] = path.read_bytes()

    def test_csv_writers_reject_an_existing_path_in_no_overwrite_mode(self):
        for writer in (self.splitter._write_csv, save_split_workbook):
            with self.subTest(writer=writer.__name__), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / 'existing.csv'
                target.write_text('original', encoding='utf-8')
                with self.assertRaises(FileExistsError):
                    writer(target, ['title'], [['new']], overwrite=False)
                self.assertEqual(target.read_text(encoding='utf-8'), 'original')

    def test_utility_splitters_preserve_outputs_across_four_runs(self):
        for mode in ('parts', 'each'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                source = self.source(folder)
                saved = {}
                base = 'sample_style_1' if mode == 'parts' else 'Tops'
                for run, suffix in enumerate(('', '_新', '_新2', '_新3')):
                    self.write_source(source, str(run))
                    if mode == 'parts':
                        stat = utility_split_parts(source, 1, overwrite=False, log=lambda *_: None)
                    else:
                        stat = utility_split_each(source, overwrite=False, log=lambda *_: None)
                    target = stat['outputs'][0]
                    self.assertEqual(target.stem, base + suffix)
                    for path, content in saved.items():
                        self.assertEqual(path.read_bytes(), content)
                    saved[target] = target.read_bytes()


if __name__ == '__main__':
    unittest.main()
