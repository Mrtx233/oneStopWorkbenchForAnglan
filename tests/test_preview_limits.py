"""Preview must count all combinations without constructing more than its row limit."""
import io
import itertools
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


APP = Path(__file__).resolve().parents[1] / 'Json Crawler system'
sys.path.insert(0, str(APP))
from common.step_loader import alias_step, load_step


class PreviewLimitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        stage = APP / 'stages' / '03_data_analysis'
        alias_step('config', stage / '00_config.py')
        cls.parser = alias_step('product_parser', stage / '30_product_parser.py')
        cls.options = alias_step('option_split', stage / '10_option_split.py')
        cls.analyzer = alias_step('analyzer', stage / '40_analyzer.py')
        cls.pipeline = load_step(stage / '99_pipeline_entry.py')

    def product(self, count=3, names=('Color', 'Size')):
        return {
            'url': 'https://example.com/products/shirt', 'title': 'Shirt', 'fennei': 'Tops',
            'price': '20', 'compare_at_price': '40', 'currency': 'USD',
            'body_html': '', 'images': [], 'md5': 'source',
            'option_counts': {name: count for name in names},
            'options': [{name: ({f'value{i}': f'https://example.com/{i}.jpg' for i in range(count)}
                                if name == 'Color' else [str(i) for i in range(count)])}
                        for name in names],
        }

    def source(self, folder, products):
        path = Path(folder) / 'example.com.json'
        path.write_text(json.dumps(products), encoding='utf-8')
        return path

    def test_trillion_combinations_generate_exactly_200_preview_entries(self):
        names = ('Color', 'Size', 'Model', 'Fit', 'Material', 'Length')
        generated = 0

        def guarded_product(*pools):
            nonlocal generated
            for combo in itertools.product(*pools):
                generated += 1
                if generated > 200:
                    raise AssertionError('Preview expanded more than 200 combinations')
                yield combo

        with tempfile.TemporaryDirectory() as folder:
            source = self.source(folder, [self.product(100, names)])
            namespace = self.parser.build_option_combos.__globals__
            with patch.dict(namespace, {'itertools_product': guarded_product}):
                rows, total, missing = self.analyzer.expand_cartesian(source, names)
            self.assertEqual((len(rows), total, missing, generated), (200, 100 ** 6, 0, 200))

    def test_total_and_missing_include_products_after_the_preview_is_full(self):
        products = [self.product(20), self.product(7, ('Size',))]
        with tempfile.TemporaryDirectory() as folder:
            source = self.source(folder, products)
            rows, total, missing = self.analyzer.expand_cartesian(source, ['Color', 'Size'])
            self.assertEqual((len(rows), total, missing), (200, 407, 1))

    def test_rows_keep_color_chunk_order_images_and_complete_sizes(self):
        product = self.product(3)
        limits = {'Color': 2, 'Size': 1}
        expected = []
        options = self.parser.get_sorted_options(product)
        for chunk in self.options.option_limit_sets(options, limits):
            sliced = self.options.restrict_product(product, chunk)
            _, _, entries = self.parser.selected_product_combinations(sliced, ['Color', 'Size'])
            expected.extend((' / '.join(entry['combo']), entry['image_url']) for entry in entries)
        with tempfile.TemporaryDirectory() as folder:
            source = self.source(folder, [product])
            rows, total, missing = self.analyzer.expand_cartesian(
                source, ['Color', 'Size'], option_limits=limits, row_limit=5)
        self.assertEqual([(row['variant_title'], row['image_url']) for row in rows], expected[:5])
        self.assertEqual((total, missing), (9, 0))

    def test_empty_dimensions_and_products_without_options_count_correctly(self):
        products = [self.product(0), self.product(0, ())]
        with tempfile.TemporaryDirectory() as folder:
            source = self.source(folder, products)
            rows, total, missing = self.analyzer.expand_cartesian(source, ['Color', 'Size'])
        self.assertEqual((len(rows), total, missing), (1, 1, 1))
        self.assertEqual(rows[0]['image_status'], 'no_opt')

    def test_zero_row_limit_counts_without_generating_any_combinations(self):
        with tempfile.TemporaryDirectory() as folder:
            source = self.source(folder, [self.product(10)])
            namespace = self.parser.build_option_combos.__globals__
            with patch.dict(namespace, {'build_option_combos': lambda *_: self.fail('expanded combinations')}):
                self.assertEqual(self.analyzer.expand_cartesian(
                    source, ['Color', 'Size'], row_limit=0), ([], 100, 0))

    def test_stopped_preview_does_not_expand_products(self):
        stop = threading.Event()
        stop.set()
        with tempfile.TemporaryDirectory() as folder:
            source = self.source(folder, [self.product(10)])
            with patch.object(self.parser, 'selected_product_combinations', side_effect=AssertionError):
                self.assertEqual(self.analyzer.expand_cartesian(
                    source, ['Color', 'Size'], stop=stop), ([], 0, 0))

    def test_pipeline_emits_bounded_rows_and_exact_total(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            project = Path(folder)
            analysis = project / 'Json' / 'Data Analysis'
            analysis.mkdir(parents=True)
            self.source(analysis, [self.product(20)])
            events = []
            self.pipeline.run({'project': str(project), 'action': 'preview'}, threading.Event(),
                              lambda event, **data: events.append((event, data)))
            preview = next(data for event, data in events if event == 'preview')
            self.assertEqual((len(preview['rows']), preview['total']), (200, 400))
            self.assertFalse((project / 'CSV').exists())


if __name__ == '__main__':
    unittest.main()
