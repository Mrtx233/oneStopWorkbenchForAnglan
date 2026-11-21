"""Offline regression checks for independent products created by color splitting."""
import copy
import csv
import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import threading
import unittest


APP = Path(__file__).resolve().parents[1] / 'Json Crawler system'
sys.path.insert(0, str(APP))
from common.step_loader import alias_step, load_step


class ColorSplitIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        analysis = APP / 'stages' / '03_data_analysis'
        cls.config = alias_step('config', analysis / '00_config.py')
        cls.parser = alias_step('product_parser', analysis / '30_product_parser.py')
        cls.options = alias_step('option_split', analysis / '10_option_split.py')
        cls.analysis_pipeline = load_step(analysis / '99_pipeline_entry.py')
        split = APP / 'stages' / '03_1_split'
        alias_step('config', split / '00_config.py')
        cls.splitter = alias_step('splitter', split / '20_split.py')
        cls.split_pipeline = load_step(split / '99_pipeline_entry.py')

    def product(self, colors=('Red', 'Blue', 'Green', 'Black', 'White')):
        url = 'https://example.com/products/shirt'
        return {
            'url': url, 'title': 'Shirt', 'fennei': 'Tops', 'body_html': '<p>Shirt</p>',
            'price': '20', 'compare_at_price': '40', 'currency': 'USD',
            'images': ['https://example.com/gallery.jpg'],
            'option_counts': {'Color': len(colors), 'Size': 2},
            'options': [
                {'Color': {color: f'https://example.com/{index}.jpg'
                           for index, color in enumerate(colors)}},
                {'Size': ['S', 'M']},
            ],
            'md5': hashlib.md5(url.encode('utf-8')).hexdigest(),
        }

    def parse(self, product, limit=2, output_products=None):
        return self.options.parse_product_rows(
            {'product': product}, selected_options=['Color', 'Size'],
            option_limits={'Color': limit}, output_products=output_products,
        )

    def read_csv(self, path):
        with open(path, encoding='utf-8-sig', newline='') as stream:
            return list(csv.DictReader(stream))

    def write_csv(self, path, rows):
        # Exercise the real header index: md5 is deliberately moved away from the end.
        fields = ['md5'] + [field for field in self.config.CSV_FIELDS if field != 'md5']
        with open(path, 'w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def export(self, project, product=None):
        product = self.product() if product is None else product
        source = project / 'Json' / 'Data Analysis' / 'example.com.json'
        source.parent.mkdir(parents=True)
        source.write_text(json.dumps([product]), encoding='utf-8')
        original = source.read_bytes()
        settings = {'project': str(project), 'options': ['Color', 'Size'],
                    'option_limits': {'Color': 2}}
        self.assertEqual(self.analysis_pipeline.run(
            settings, threading.Event(), lambda *args, **kwargs: None), 'success')
        self.assertEqual(source.read_bytes(), original)
        return project / 'CSV' / 'example.com_style.csv'

    def test_color_products_have_distinct_stable_ids_and_matching_json(self):
        product = self.product()
        original = copy.deepcopy(product)
        products = []
        rows = self.parse(product, output_products=products)
        self.assertEqual(len(rows), 3)
        ids = [row['md5'] for row in rows]
        self.assertEqual(len(set(ids)), 3)
        self.assertNotIn(product['md5'], ids)
        self.assertEqual(ids, [row['md5'] for row in self.parse(product)])
        self.assertEqual(ids, [item['md5'] for item in products])
        self.assertEqual([item['option_counts']['Color'] for item in products], [2, 2, 1])
        for row, item in zip(rows, products):
            self.assertRegex(row['md5'], r'^[0-9a-f]{32}$')
            self.assertEqual(item['options'][1], {'Size': ['S', 'M']})
            self.assertEqual(item['option_counts']['Size'], 2)
            self.assertEqual(row['src_links'].split('#'), item['images'])
        self.assertEqual(product, original)

    def test_identity_ignores_color_order_prices_and_images(self):
        product = self.product(('Red', 'Blue'))
        products = []
        self.parse(product, limit=1, output_products=products)
        expected = {next(iter(item['options'][0]['Color'])): item['md5'] for item in products}
        changed = copy.deepcopy(product)
        changed['price'] = '25'
        changed['options'][0]['Color'] = {
            'Blue': 'https://example.com/new-blue.jpg',
            'Red': 'https://example.com/new-red.jpg',
        }
        products = []
        self.parse(changed, limit=1, output_products=products)
        actual = {next(iter(item['options'][0]['Color'])): item['md5'] for item in products}
        self.assertEqual(actual, expected)

    def test_unsplit_products_keep_their_original_id(self):
        product = self.product(('Red', 'Blue'))
        self.assertEqual(self.parse(product)[0]['md5'], product['md5'])
        rows = self.options.parse_product_rows(
            product, selected_options=['Size'], option_limits={'Color': 1})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['md5'], product['md5'])

    def test_legacy_products_without_md5_use_source_url(self):
        product = self.product()
        del product['md5']
        ids = {row['md5'] for row in self.parse(product)}
        self.assertEqual(len(ids), 3)
        self.assertEqual(ids, {row['md5'] for row in self.parse(product)})
        product['url'] = 'https://example.com/products/other-shirt'
        self.assertTrue(ids.isdisjoint(row['md5'] for row in self.parse(product)))

    def test_failed_later_color_does_not_leave_partial_json_records(self):
        product = self.product(('Red', 'x' * 33000))
        products = []
        with self.assertRaises(self.parser.StylesTooLongError):
            self.parse(product, limit=1, output_products=products)
        self.assertEqual(products, [])

    def test_export_and_both_split_modes_keep_csv_and_json_in_sync(self):
        for mode in ('parts', 'each'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
                project = Path(folder)
                source_csv = self.export(project)
                rows = self.read_csv(source_csv)
                self.write_csv(source_csv, list(reversed(rows)))
                companion = json.loads(source_csv.with_suffix('.json').read_text(encoding='utf-8'))
                self.assertEqual({row['md5'] for row in rows}, {item['md5'] for item in companion})
                status = self.split_pipeline.run(
                    {'project': str(project), 'split_mode': mode, 'split_parts': 2},
                    threading.Event(), lambda *args, **kwargs: None)
                self.assertEqual(status, 'success')
                outputs = sorted((project / 'CSV').glob('**/csv/*.csv'))
                self.assertEqual(len(outputs), 2 if mode == 'parts' else 1)
                all_ids, all_colors = [], []
                for output in outputs:
                    csv_rows = self.read_csv(output)
                    target = output.parent.parent / 'json' / output.with_suffix('.json').name
                    products = json.loads(target.read_text(encoding='utf-8'))
                    self.assertEqual({row['md5'] for row in csv_rows}, {item['md5'] for item in products})
                    all_ids.extend(item['md5'] for item in products)
                    for item in products:
                        all_colors.extend(item['options'][0]['Color'])
                self.assertEqual(len(all_ids), 3)
                self.assertEqual(len(set(all_ids)), 3)
                self.assertCountEqual(all_colors, ['Red', 'Blue', 'Green', 'Black', 'White'])

    def test_separate_woocommerce_exports_have_disjoint_stable_skus(self):
        wp = load_step(APP / 'stages' / '04_price_export' / '14_export_wp.py')
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            project = Path(folder)
            source_csv = self.export(project)
            self.split_pipeline.run(
                {'project': str(project), 'split_mode': 'parts', 'split_parts': 2},
                threading.Event(), lambda *args, **kwargs: None)
            all_skus = set()
            for index, output in enumerate(sorted((project / 'CSV').glob('**/csv/*.csv'))):
                target = project / f'wp-{index}.csv'
                wp.convert_to_wp(str(output), str(target))
                rows = self.read_csv(target)
                skus = {row['SKU'] for row in rows}
                self.assertEqual(len(skus), len(rows))
                self.assertTrue(all_skus.isdisjoint(skus))
                all_skus.update(skus)
                # Product identity must survive a different row order on a repeat export.
                self.write_csv(output, list(reversed(self.read_csv(output))))
                wp.convert_to_wp(str(output), str(target))
                self.assertEqual(skus, {row['SKU'] for row in self.read_csv(target)})
                self.assertEqual(wp.check_wp_skus(target), {'duplicates': {}, 'orphans': []})

    def test_old_csv_without_companion_json_uses_analysis_json(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            project = Path(folder)
            source_csv = self.export(project, self.product(('Red',)))
            source_csv.with_suffix('.json').unlink()
            self.assertEqual(self.split_pipeline.run(
                {'project': str(project), 'split_mode': 'parts', 'split_parts': 2},
                threading.Event(), lambda *args, **kwargs: None), 'success')
            products = []
            for path in (project / 'CSV').glob('**/json/*.json'):
                products.extend(json.loads(path.read_text(encoding='utf-8')))
            self.assertEqual([item['md5'] for item in products], [self.product()['md5']])

    def test_missing_color_product_json_is_reported_before_writing_empty_json(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            project = Path(folder)
            source_csv = self.export(project)
            rows = self.read_csv(source_csv)
            products = [self.product()]
            with self.assertRaisesRegex(ValueError, 'JSON.*md5'):
                self.splitter.split_json_by_md5(
                    products, {str(project / 'part.csv'): {row['md5'] for row in rows}})
            self.assertFalse((project / 'part.json').exists())


if __name__ == '__main__':
    unittest.main()
