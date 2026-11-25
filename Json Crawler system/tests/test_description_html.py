"""从仓库根运行：python -B -m unittest discover -s "Json Crawler system/tests"。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.description_html import clean_body_html
from common.description_policy import DESCRIPTION_KEYWORDS, scan_description_keywords
from common.product_model import Product


class DescriptionCleaningTests(unittest.TestCase):
    def assert_no_keywords(self, html):
        self.assertEqual({word: count for word, count in scan_description_keywords(html).items()
                          if count}, {})

    def test_all_requested_keywords(self):
        for word in DESCRIPTION_KEYWORDS:
            for variant in (word, word.upper(), word.swapcase()):
                with self.subTest(word=variant):
                    result = clean_body_html(f'<div><p>Soft cotton.</p><p>{variant}</p></div>')
                    self.assert_no_keywords(result)
                    self.assertIn('Soft cotton.', result)

    def test_embedded_and_split_identifiers(self):
        identifiers = [
            ('Product ID: CDAZPDAWKO', 'CDAZPDAWKO'),
            ('<strong>Product ID</strong><span>:Q8ZQN89521</span>', 'Q8ZQN89521'),
            ('Product <b>ID: CDAZ</b>PDAWKO', 'CDAZPDAWKO'),
            ('SPU: DZ-336030-LYL1', 'DZ-336030-LYL1'),
            ('SPU: INS-335203-LYL1', 'INS-335203-LYL1'),
            ('SPU: OWO707901', 'OWO707901'),
            ('<span>SPU: </span><b>DZ-332422-YJ</b>', 'DZ-332422-YJ'),
            ('Article number：xhjn52022031951', 'xhjn52022031951'),
            ('<font><span>Article number</span></font><span>：</span>'
             '<span>xhjn52022031951</span>', 'xhjn52022031951'),
        ]
        for identifier, code in identifiers:
            for raw in (f'<p>{identifier}</p>',
                        f'<p>Soft cotton. {identifier} Easy to wear.</p>'):
                with self.subTest(identifier=identifier, raw=raw):
                    result = clean_body_html(raw)
                    self.assert_no_keywords(result)
                    self.assertNotIn(code, result)
                    if 'Soft cotton' in raw:
                        self.assertIn('Soft cotton.', result)
                        self.assertIn('Easy to wear.', result)
                    else:
                        self.assertEqual(result, '')

    def test_policy_paragraphs(self):
        policies = [
            'STANDARD SHIPPING', 'DO YOU SHIP INTERNATIONALLY?', 'IMPORT TAXES AND DUTIES',
            'UNITED STATE AND OTHER COUNTRIES SHIPPING COST',
            'HOW LONG DOES SHIPPING NORMALLY TAKE?', 'HOW CAN I GET MY TRACKING CODE?',
            'HOW DO I TRACK MY ORDER?', 'Processing Time: 3 days', 'Stocking Time: 2 days',
            'Test Time: 1 day', 'Receiving Time: 8 days', 'Delivery Time: 5 days',
            'Free shipping over $69', 'Pre-order takes 20 days', '预购需要十天',
            'Refund', 'Return Policy', 'Returns & Exchanges',
            '30-Day No Questions Asked Return', 'Satisfaction Guarantee',
            'Risk-Free Purchase', 'AFTER-SALE SERVICE', '退款地址', '退货地址',
            'Payment', 'Payment Method', 'PayPal', 'Credit/Debit Card',
            'How Do I Pay For My Order?', 'What Currencies Can I Use?',
            'Your payment was declined', '3D Secure', 'Card Issuer',
            'Privacy Policy', 'personal information', 'SSL / Secure Socket Layer',
            'Terms and Conditions', 'cookies', 'GDPR', 'information we collect',
        ]
        for policy in policies:
            with self.subTest(policy=policy):
                result = clean_body_html(f'<p>Useful fabric.</p><p>Before {policy}. After.</p>')
                self.assertEqual(result, '<p>Useful fabric.</p>')
                self.assert_no_keywords(result)

    def test_keywords_split_by_inline_tags_and_entities(self):
        for policy in ('Free ship<b>ping</b> over $69.',
                       'Personal&nbsp;<b>information</b> is collected.',
                       'Email support&#64;example.com',
                       'Why <strong>us</strong>', 'After–sale service',
                       'pay\u200bpal accepted', 'Credit <em>Card</em>'):
            with self.subTest(policy=policy):
                result = clean_body_html(f'<p>Fabric: cotton</p><p>{policy}</p>')
                self.assertEqual(result, '<p>Fabric: cotton</p>')

    def test_policy_heading_removes_following_body_until_peer_heading(self):
        raw = ('<h2>Fabric</h2><p>100% cotton</p>'
               '<h2>STANDARD SHIPPING</h2><p>Allow 7–15 business days.</p>'
               '<h3>Timing details</h3><p>Usually two weeks.</p>'
               '<h2>Care</h2><p>Wash cold.</p>')
        self.assertEqual(clean_body_html(raw),
                         '<h2>Fabric</h2><p>100% cotton</p><h2>Care</h2><p>Wash cold.</p>')

    def test_plain_policy_heading(self):
        for heading in ('Payment Method', '<span>Payment Method</span>'):
            with self.subTest(heading=heading):
                raw = (f'<p>Soft cotton.</p><p>{heading}</p><p>Choose one at checkout.</p>'
                       '<h3>Fabric</h3><p>Wool blend.</p>')
                self.assertEqual(clean_body_html(raw),
                                 '<p>Soft cotton.</p><h3>Fabric</h3><p>Wool blend.</p>')

    def test_identifier_heading_does_not_swallow_product_paragraphs(self):
        for heading in ('<h2>Product ID</h2>', '<p>SPU</p>', '<p>Article number</p>'):
            with self.subTest(heading=heading):
                self.assertEqual(clean_body_html(heading + '<p>Soft cotton.</p>'),
                                 '<p>Soft cotton.</p>')

    def test_bold_policy_in_table_keeps_cell_positions(self):
        raw = '<table><tr><td><b>PayPal</b></td><td>Size M</td></tr></table>'
        self.assertEqual(clean_body_html(raw, keep_tables=True),
                         '<table><tr><td></td><td>Size M</td></tr></table>')

    def test_wrapped_policy_heading_and_body(self):
        raw = ('<div><div><h3>Shipping</h3></div><div><p>Allow two weeks.</p></div></div>'
               '<section><h3>Features</h3><p>Soft cotton.</p></section>')
        self.assertEqual(clean_body_html(raw),
                         '<section><h3>Features</h3><p>Soft cotton.</p></section>')

    def test_product_section_after_policy_resumes_inside_container(self):
        raw = ('<h2>Shipping</h2><p>Allow two weeks.</p>'
               '<section><h2>Fabric</h2><p>Soft cotton.</p></section>')
        self.assertEqual(clean_body_html(raw),
                         '<section><h2>Fabric</h2><p>Soft cotton.</p></section>')

    def test_root_text_lines(self):
        self.assertEqual(clean_body_html('Soft cotton\nFree shipping\nWash cold'),
                         'Soft cotton\nWash cold')

    def test_identifier_removal_leaves_no_empty_breaks_or_repeated_spaces(self):
        raw = ('<div><p><b>SPU:</b> OWO707901<br></p>'
               '<p>Soft cotton. SPU: DZ-336030-LYL1 Easy to wear.</p></div>')
        result = clean_body_html(raw)
        self.assertEqual(result, '<div><p>Soft cotton. Easy to wear.</p></div>')
        self.assertEqual(clean_body_html(result), result)

    def test_images_tables_and_article_have_zero_raw_residue(self):
        raw = ('<article><p>Soft cotton.</p></article>'
               '<img src="https://artswardrobe.com/x.jpg">'
               '<img src="https://example.com/cotton.jpg" alt="shipping">'
               '<table><tr><td colspan="2">Size</td><td>PayPal accepted</td>'
               '<td><b>SPU:</b> OWO707901</td></tr></table>')
        result = clean_body_html(raw, keep_images=True, keep_tables=True)
        self.assert_no_keywords(result)
        self.assertIn('<p>Soft cotton.</p>', result)
        self.assertIn('<img src="https://example.com/cotton.jpg">', result)
        self.assertIn('<td colspan="2">Size</td><td></td><td></td>', result)
        self.assertNotIn('OWO707901', result)

    def test_existing_cleaning_and_normal_product_content(self):
        raw = ('<div class="x"><p>Fabric: 100% cotton. This dress is made in Italy.</p>'
               '<ul><li>V neck</li><li>Length: 80 cm</li><li>Color: navy</li></ul>'
               '<p>Made in Italy</p><p>SKU:123</p><a href="x">Link</a>'
               '<script>alert(1)</script><img src="x.jpg"></div>')
        expected = ('<div><p>Fabric: 100% cotton. This dress is made in Italy.</p>'
                    '<ul><li>V neck</li><li>Length: 80 cm</li><li>Color: navy</li></ul></div>')
        self.assertEqual(clean_body_html(raw), expected)

    def test_product_model_applies_rules_for_new_and_existing_records(self):
        product = Product(url='https://example.com/products/test', title='Cotton',
                          fennei='Dresses', price='10', compare_at_price='20',
                          body_html='<p>Soft cotton. SPU: OWO707901</p><p>Free shipping</p>')
        self.assert_no_keywords(product.body_html)
        self.assertNotIn('OWO707901', product.body_html)
        row = product.to_dict()
        row['body_html'] += '<p>Privacy Policy</p>'
        self.assertEqual(Product.from_dict(row).body_html, product.body_html)

    def test_idempotence_with_keywords_and_entities(self):
        raw = ('<article><p>A &amp; B. Product ID: CDAZPDAWKO</p>'
               '<p>Made in Italy. <b>Soft cotton.</b></p>'
               '<h2>SHIPPING</h2><p>Two weeks.</p></article>')
        cleaned = clean_body_html(raw, keep_images=True, keep_tables=True)
        self.assertEqual(clean_body_html(cleaned, keep_images=True, keep_tables=True), cleaned)
        self.assert_no_keywords(cleaned)

    def test_email_deletes_entire_paragraph_before_link_removal(self):
        emails = ('service@artswardrobe.com', 'shine@users-care.com',
                  'service@online-supportmail.com', 'support@marvelousee.com',
                  'arbitrary.name+orders@another-store.example')
        for email in emails:
            for address in (email, email.replace('@', '&#64;'),
                            f'<a href="mailto:{email}">Contact us</a>',
                            email.replace('@', '<b>@</b>')):
                with self.subTest(address=address):
                    raw = f'<p>Fabric: Cotton.</p><p>Email us anytime at {address}. We can help.</p>'
                    self.assertEqual(clean_body_html(raw), '<p>Fabric: Cotton.</p>')

    def test_external_domains_and_social_traffic(self):
        destinations = ('artswardrobe.com', 'wowweary.com', 'artsweary.com',
                        'users-care.com', 'online-supportmail.com', 'marvelousee.com',
                        'facebook', 'instagram', 'youtube', 'tiktok', 'twitter', 'pinterest')
        for destination in destinations:
            for reference in (destination, f'<a href="https://{destination}/">Visit us</a>'):
                with self.subTest(reference=reference):
                    raw = f'<p>Fabric: Cotton.</p><p>More updates: {reference}</p>'
                    self.assertEqual(clean_body_html(raw), '<p>Fabric: Cotton.</p>')

    def test_store_copy_and_size_navigation(self):
        phrases = ('WHY US', 'Anniversary promotion', 'Buy 2 Pcs Get Free Shipping',
                   'Thank you very much for visiting our store', 'Happy Shopping',
                   'Add to Cart', 'Trusted by 10K+ happy customers', 'Price is limited',
                   'See more：Vacation', 'How to choose your size?', 'Fit Finder',
                   'Size guide help you', 'Size guide can help you choose')
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                result = clean_body_html(f'<p>Fabric: Cotton.</p><p>{phrase}</p>')
                self.assertEqual(result, '<p>Fabric: Cotton.</p>')

    def test_policy_only_faq_is_empty(self):
        descriptions = (
            '<h1>FAQ</h1><h2>Can I cancel my order?</h2><p>Please contact our team first.</p>',
            '<h1>FAQ</h1><p>Shipping</p><p>Allow two weeks.</p>'
            '<h2>Can I change my order?</h2><p>Please contact our team first.</p>',
            '<p>Payment Method</p><p>Choose one at checkout.</p>'
            '<p>Need help?</p><p>Contact us</p>',
            '<div><h2>Refund Policy</h2><p>Send it back within thirty days.</p></div>'
            '<p>Contact us</p>',
            '<p>Welcome to our store</p><p>Privacy Policy</p><p>Contact us</p>',
        )
        for raw in descriptions:
            with self.subTest(raw=raw):
                self.assertEqual(clean_body_html(raw), '')

    def test_missing_field_names_does_not_mean_policy_only(self):
        for product in ('Soft cotton with a round neckline.',
                        'A lightweight floral dress with side pockets.'):
            with self.subTest(product=product):
                result = clean_body_html('<h1>FAQ</h1><h2>Shipping</h2><p>Allow two weeks.</p>'
                                         f'<h2>Features</h2><p>{product}</p>')
                self.assertIn(product, result)

    def test_policy_only_faq_garment_names_are_not_product_details(self):
        for item in ('dress', 'sweater', 'cotton garment'):
            with self.subTest(item=item):
                raw = ('<h1>FAQ</h1><h2>Return Policy</h2>'
                       f'<p>How can I return my {item}?</p>'
                       '<h2>Can I change my order?</h2><p>Please contact our team first.</p>')
                self.assertEqual(clean_body_html(raw), '')

    def test_exact_duplicate_details_blocks_keep_one(self):
        block = '<section><h2>Product Details</h2><p>Fabric: Cotton.</p><p>Pattern: Floral.</p></section>'
        result = clean_body_html(block + block)
        self.assertEqual(result, block)

    def test_duplicate_paragraphs_across_different_wrappers(self):
        raw = ('<div><h2>Product Details</h2><p>Fabric: Cotton.</p><p>Pattern: Floral.</p></div>'
               '<section><h3>Product Details</h3><p><b>Fabric:</b> Cotton.</p>'
               '<p>Pattern:  Floral.</p><p>Length: 80 cm.</p></section>')
        result = clean_body_html(raw)
        self.assertEqual(result.count('Product Details'), 1)
        self.assertEqual(result.count('Cotton.'), 1)
        self.assertEqual(result.count('Floral.'), 1)
        self.assertIn('Length: 80 cm.', result)
        self.assertEqual(clean_body_html(result), result)

    def test_different_values_and_table_rows_are_not_deduplicated(self):
        raw = ('<p>Color: Navy.</p><p>Color: Red.</p>'
               '<table><tr><th>Size</th><th>Length</th></tr>'
               '<tr><td>M</td><td>80</td></tr><tr><td>M</td><td>80</td></tr></table>')
        result = clean_body_html(raw, keep_tables=True)
        self.assertIn('Color: Navy.', result)
        self.assertIn('Color: Red.', result)
        self.assertEqual(result.count('<tr><td>M</td><td>80</td></tr>'), 2)

    def test_different_image_blocks_are_preserved(self):
        raw = ('<div><p>Navy.</p><img src="navy.jpg"></div>'
               '<div><p>Navy.</p><img src="navy-detail.jpg"></div>')
        result = clean_body_html(raw, keep_images=True)
        self.assertIn('src="navy.jpg"', result)
        self.assertIn('src="navy-detail.jpg"', result)

    def test_new_rules_are_stable_for_all_image_and_table_modes(self):
        raw = ('<h2>Product Details</h2><p>Fabric: Cotton.</p><p>Fabric: Cotton.</p>'
               '<p>Email us at <a href="mailto:hello@any-store.example">this address</a>.</p>'
               '<p>Fit Finder</p><img src="cotton.jpg">')
        for images in (False, True):
            for tables in (False, True):
                with self.subTest(images=images, tables=tables):
                    result = clean_body_html(raw, keep_images=images, keep_tables=tables)
                    self.assertEqual(result.count('Fabric: Cotton.'), 1)
                    self.assert_no_keywords(result)
                    self.assertEqual(clean_body_html(result, keep_images=images, keep_tables=tables), result)

    def test_product_description_resumes_below_higher_policy_heading(self):
        raw = ('<h3>Buy 2 Pcs Get Free Shipping</h3><h4>Product description</h4>'
               '<div>Soft lightweight stretch fabric.</div><p>Pattern: Floral.</p>')
        self.assertEqual(clean_body_html(raw),
                         '<h4>Product description</h4><div>Soft lightweight stretch fabric.</div>'
                         '<p>Pattern: Floral.</p>')

    def test_product_heading_with_spaced_colon_resumes_content(self):
        for title in ('Product Details :', 'Size Chart ：', 'Fabric :'):
            with self.subTest(title=title):
                raw = ('<h2>Shipping</h2><p>Allow two weeks.</p>'
                       f'<h4>{title}</h4><p>Cotton with side pockets.</p>')
                self.assertIn('Cotton with side pockets.', clean_body_html(raw))

    def test_plain_product_heading_resumes_content(self):
        for title in ('Product description', 'Product Details :', 'Fabric'):
            with self.subTest(title=title):
                raw = ('<h2>Shipping</h2><p>Allow two weeks.</p>'
                       f'<p>{title}</p><p>Cotton with side pockets.</p>')
                self.assertIn('Cotton with side pockets.', clean_body_html(raw))

    def test_promotion_and_product_separated_by_breaks_keep_product(self):
        raw = ('<p><strong><span>Anniversary promotion<br></span>'
               'Click on ADD TO CART to get yours now!</strong><br><br>'
               '<strong>Product Details</strong><br>Soft cotton with side pockets.<br>'
               'Size Chart:<br>Length: 80 cm.</p>')
        result = clean_body_html(raw)
        self.assert_no_keywords(result)
        self.assertIn('Soft cotton with side pockets.', result)
        self.assertIn('Length: 80 cm.', result)
        self.assertEqual(clean_body_html(result), result)

    def test_email_still_deletes_entire_paragraph_with_breaks(self):
        raw = '<p>Fabric: Cotton.<br>Email service@example.com for help.</p>'
        self.assertEqual(clean_body_html(raw), '')


if __name__ == '__main__':
    unittest.main()
