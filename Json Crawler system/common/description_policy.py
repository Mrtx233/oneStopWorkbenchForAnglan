"""删除货号、店铺政策与引流文案，清空纯政策描述并合并重复商品段落。"""
import re
from dataclasses import dataclass, field
from html import escape, unescape
from html.parser import HTMLParser


# 按要求做不区分大小写的子串检查，currenc 同时覆盖 currency / currencies。
DESCRIPTION_KEYWORDS = (
    'Product ID', 'SPU', 'Article', 'shipping', 'delivery', 'refund', 'return',
    'payment', 'paypal', 'credit card', 'currenc', 'privacy',
    'personal information', 'terms', '@', 'artswardrobe', 'wowweary',
    'artsweary', 'users-care', 'supportmail', 'marvelousee', 'facebook',
    'instagram', 'see more', 'why us', 'sold out', 'tracking', 'insurance',
    'tax', 'duties', 'postal', 'courier', 'customs', 'ShippingDelivery',
    'after-sale',
    'youtube', 'tiktok', 'twitter', 'pinterest', 'Anniversary promotion',
    'Thank you very much for visiting our store', 'Happy Shopping', 'Add to Cart',
    'Trusted by 10K+ happy customers', 'Price is limited',
    'How to choose your size', 'Fit Finder', 'Size guide help you',
)


def _term_pattern(term):
    # 标签拆开的词由树文本拼回；词间也允许换行、NBSP、无空格及不同横杠。
    return r'\s*'.join(re.escape(word).replace(r'\-', r'[-\s\u2010-\u2015]*')
                       for word in term.split())


KEYWORD_PATTERNS = {term: re.compile(_term_pattern(term), re.I)
                    for term in DESCRIPTION_KEYWORDS}
KEYWORD_PATTERN = re.compile('|'.join(pattern.pattern for pattern in KEYWORD_PATTERNS.values()), re.I)
POLICY_PATTERN = re.compile(
    KEYWORD_PATTERN.pattern
    + r'|\b(?:processing|stocking|test|receiving)\s*time\b'
    + r'|\bpre[-\s]?order\b|\bship\s+internationally\b'
    + r'|\bhow\s+do\s+i\s+track\s+my\s+order\b'
    + r'|\bsatisfaction\s+guarantee\b|\brisk[-\s]?free\s+purchase\b'
    + r'|\bhow\s+do\s+i\s+pay\s+for\s+my\s+order\b'
    + r'|\b(?:credit\s*/\s*)?debit\s*card\b|\b3d\s*secure\b|\bcard\s*issuer\b'
    + r'|\bssl\b|\bsecure\s+sockets?\s+layer\b|\bcookies?\b|\bgdpr\b'
    + r'|\binformation\s+we\s+collect\b|预购|退款|退货|换货'
    + r'|\btrusted\s+by\s+10\s*k\s*\+?\s*happy\s*customers\b'
    + r'|\bhow\s+to\s+choose\s+(?:your|the\s+right)\s+size\b'
    + r'|\bsize\s+guides?\s+(?:can\s+)?help\s+you\b',
    re.I,
)
POLICY_HEADING_PATTERN = re.compile(
    r'(?:standard\s+|international\s+|worldwide\s+)?shipping(?:\s+(?:information|policy|cost))?'
    r'|(?:returns?|refunds?)(?:\s+policy|\s*(?:&|and)?\s*exchanges?)?'
    r'|\d+[-\s]day\s+no\s+questions\s+asked\s+return'
    r'|payment(?:\s+methods?)?|privacy(?:\s+policy)?|terms(?:\s+and\s+conditions)?'
    r'|after[-\s]?sale(?:\s+service)?|satisfaction\s+guarantee|risk[-\s]?free\s+purchase'
    r'|why\s*us|fit\s*finder|how\s+to\s+choose\s+your\s+size'
    r'|anniversary\s+promotion|happy\s+shopping',
    re.I,
)
IDENTIFIER_PATTERN = re.compile(
    r'(?i:product\s*id)\s*[:：#=\-]?\s*[A-Z0-9]{10}(?![A-Za-z0-9])'
    r'|(?i:spu(?:\s*货号)?|article\s*(?:number|no\.?))\s*[:：#=\-]?\s*'
    r'(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*'
)
VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
             'link', 'meta', 'param', 'source', 'track', 'wbr'}
BLOCK_TAGS = {'address', 'article', 'aside', 'blockquote', 'dd', 'details',
              'div', 'dl', 'dt', 'fieldset', 'figcaption', 'figure', 'footer',
              'form', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hr',
              'li', 'main', 'nav', 'ol', 'p', 'pre', 'section', 'summary',
              'table', 'tbody', 'td', 'tfoot', 'th', 'thead', 'tr', 'ul'}
PARAGRAPH_TAGS = {'p', 'li', 'td', 'th', 'dt', 'dd', 'pre', 'figcaption',
                  'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'summary'}
TABLE_TAGS = {'table', 'colgroup', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th'}
HIDDEN_TAGS = {'script', 'style', 'template', 'noscript', 'svg', 'video', 'iframe', 'object'}
PRODUCT_FIELD_PATTERN = re.compile(
    r'\b(?:spu|sku|fabric|pattern|product\s*(?:id|details|description|features)|size\s*(?:chart|table)|model)\b'
    r'|面料|材质|成分|图案|领型|袖长|衣长|版型|模特|商品详情|产品详情|尺码表',
    re.I,
)
PRODUCT_INFO_PATTERN = re.compile(
    PRODUCT_FIELD_PATTERN.pattern
    + r'|\b(?:material|composition|neckline|sleeves?|length|waist|bust|hips?|lining|'
    r'color|colour|measurements?|dimensions?|weight|package|fit|style|occasion)\s*[:：]'
    r'|\b(?:cotton|polyester|chiffon|linen|wool|silk|denim|leather|lace|knit|'
    r'corduroy|viscose|spandex|elastane|nylon|rayon|velvet|satin|fleece|'
    r'dress|shirt|blouse|pants|trousers|skirt|jacket|coat|sweater|hoodie|'
    r'neckline|sleeves?|pockets?|drawstring|embroidered|floral|stretchy)\b',
    re.I,
)
FAQ_TITLE_PATTERN = re.compile(
    r'^(?:faq(?:s)?|frequently\s+asked\s+questions|questions\s*(?:and|&)\s*answers'
    r'|help\s*cent(?:er|re)|customer\s*(?:service|support)|contact\s*us)\b', re.I,
)
GENERIC_SERVICE_PATTERN = re.compile(
    r'^(?:faq(?:s)?|frequently\s+asked\s+questions|questions\s*(?:and|&)\s*answers'
    r'|contact\s*us|need\s*help|customer\s*(?:service|support)|help\s*cent(?:er|re)'
    r'|welcome(?:\s+to\s+our\s+(?:store|shop))?)[\s.!?:：]*$', re.I,
)
PRODUCT_HEADING_PATTERN = re.compile(
    r'(?:product\s*)?(?:details|description|features|specifications)'
    r'|about\s+this\s+product|fabric(?:\s*(?:and|&)\s*care)?|material|pattern'
    r'|size\s*(?:chart|table)(?:\s+for\s+\w+)?|model(?:\s+(?:info|information))?', re.I,
)


def _normalized(text):
    text = re.sub(r'[\u200b-\u200d\ufeff]', '', unescape(text))
    return re.sub(r'[\u2010-\u2015]', '-', text)


@dataclass
class _Text:
    value: str


@dataclass
class _Node:
    tag: str
    attrs: list = field(default_factory=list)
    children: list = field(default_factory=list)
    closed: bool = False


def _text(node):
    if isinstance(node, _Text):
        return node.value
    return ''.join(('\n' + _text(child) + '\n') if isinstance(child, _Node)
                   and child.tag in BLOCK_TAGS else _text(child)
                   for child in node.children)


def _policy_text(node):
    # 邮箱或外站只在链接地址中出现时，也要删除所属段落，避免基础清洗删 a 后失去线索。
    def links(current):
        if isinstance(current, _Text):
            return []
        values = [value for name, value in current.attrs
                  if current.tag == 'a' and name == 'href' and value]
        for child in current.children:
            values.extend(links(child))
        return values

    addresses = links(node)
    return _text(node) + ('\n' + '\n'.join(addresses) if addresses else '')


def _drop_hidden_nodes(node):
    node.children = [child for child in node.children
                     if not isinstance(child, _Node) or child.tag not in HIDDEN_TAGS]
    for child in node.children:
        if isinstance(child, _Node):
            _drop_hidden_nodes(child)


def _split_mixed_paragraphs(root):
    # 源站常把促销和商品正文挤在同一个 p 里，以 br 分段；邮箱仍要求整个 p 删除。
    def split_inline(node):
        if isinstance(node, _Text):
            return [[node]]
        if node.tag == 'br':
            return [[], []]
        groups = [[]]
        for child in node.children:
            pieces = split_inline(child)
            groups[-1].extend(pieces[0])
            groups.extend(pieces[1:])
        return [[_Node(node.tag, list(node.attrs), group, node.closed)] if group else []
                for group in groups]

    def has_break(node):
        return isinstance(node, _Node) and (node.tag == 'br' or
               any(has_break(child) for child in node.children))

    def visit(node):
        children = []
        for child in node.children:
            if isinstance(child, _Node):
                text = _normalized(_policy_text(child))
                if (child.tag == 'p' and has_break(child) and '@' not in text
                        and POLICY_PATTERN.search(text) and PRODUCT_INFO_PATTERN.search(text)):
                    for group in split_inline(child):
                        children.extend(group)
                    continue
                visit(child)
            children.append(child)
        node.children = children

    visit(root)


class _DescriptionTree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node('')
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack[index].closed = True
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(_Text(data))


def _remove_identifiers(root):
    # 记录文字在整棵树中的偏移，跨 span/b/strong 的标签与货号一次性删除。
    fragments, leaves = [], []
    offset = 0

    def visit(node):
        nonlocal offset
        if isinstance(node, _Text):
            leaves.append((node, offset, offset + len(node.value)))
            fragments.append(node.value)
            offset += len(node.value)
            return
        if node.tag in BLOCK_TAGS:
            fragments.append('\n')
            offset += 1
        for child in node.children:
            visit(child)
        if node.tag in BLOCK_TAGS:
            fragments.append('\n')
            offset += 1

    visit(root)
    matches = list(IDENTIFIER_PATTERN.finditer(''.join(fragments)))
    match_index = 0
    for leaf, start, end in leaves:
        while match_index < len(matches) and matches[match_index].end() <= start:
            match_index += 1
        cursor, kept = 0, []
        for match in matches[match_index:]:
            if match.start() >= end:
                break
            left, right = max(0, match.start() - start), min(end - start, match.end() - start)
            kept.append(leaf.value[cursor:left])
            cursor = right
        kept.append(leaf.value[cursor:])
        leaf.value = ''.join(kept)


def _heading(node):
    """识别标题和仅包着标题的容器，让后续无关键词的政策正文也被删除。"""
    if isinstance(node, _Text) or node.tag in TABLE_TAGS:
        return None
    if re.fullmatch(r'h[1-6]', node.tag):
        return int(node.tag[1]), _text(node)
    meaningful = [child for child in node.children
                  if not isinstance(child, _Text) or child.value.strip()]
    if len(meaningful) == 1 and isinstance(meaningful[0], _Node):
        child = meaningful[0]
        if child.tag in {'b', 'strong'} and len(_text(child)) <= 160:
            return 6, _text(child)
        nested = _heading(child)
        if nested is not None:
            return nested
    text = _normalized(_text(node)).strip()
    if node.tag in {'p', 'div', 'summary'} and text and len(text) <= 160:
        title = text.rstrip(':：').strip()
        if (text.isupper() or text.endswith('?') or POLICY_HEADING_PATTERN.fullmatch(title)
                or PRODUCT_HEADING_PATTERN.fullmatch(title)):
            return 6, text
    return None


def _policy_heading(text):
    text = _normalized(text)
    # 货号标签只删除自身，不能被当作物流/售后章节的开始吞掉后续商品段落。
    return (POLICY_PATTERN.search(text) is not None
            and re.search(r'product\s*id|spu|article', text, re.I) is None)


def _leading_heading(node):
    if isinstance(node, _Text):
        return None
    heading = _heading(node)
    if heading is not None:
        return heading
    for child in node.children:
        if isinstance(child, _Text) and not child.value.strip():
            continue
        return _leading_heading(child)
    return None


def _is_block(node):
    return isinstance(node, _Node) and (node.tag in BLOCK_TAGS or
           any(_is_block(child) for child in node.children))


def _filter_node(node):
    text = _normalized(_policy_text(node))
    # 段落先整体判断，不能先删除内部 span 而留下半句政策或孤立编号。
    if node.tag and (node.tag in PARAGRAPH_TAGS or
                     not any(_is_block(child) for child in node.children)):
        if POLICY_PATTERN.search(text):
            if node.tag in {'td', 'th'}:
                node.children = []
                return node
            return None
    kept, inline = [], []
    skip_level = None

    def flush_inline():
        if inline and skip_level is None:
            # 无标签的正文按行处理，inline 标签中的词先拼接后匹配。
            if all(isinstance(child, _Text) for child in inline):
                for child in inline:
                    value = ''.join(line for line in child.value.splitlines(keepends=True)
                                    if not POLICY_PATTERN.search(_normalized(line)))
                    if value:
                        kept.append(_Text(value))
            elif not POLICY_PATTERN.search(_normalized(''.join(_policy_text(child) for child in inline))):
                kept.extend(inline)
        inline.clear()

    for child in node.children:
        if not _is_block(child):
            inline.append(child)
            continue
        flush_inline()
        heading = _heading(child)
        if heading is not None:
            level, title = heading
            if _policy_heading(title):
                skip_level = level if skip_level is None else min(level, skip_level)
                continue
        if skip_level is not None:
            resume = heading or _leading_heading(child)
            if resume is not None and not _policy_heading(resume[1]):
                product_heading = PRODUCT_HEADING_PATTERN.fullmatch(
                    _normalized(resume[1]).strip().rstrip(':：').strip())
                if resume[0] <= skip_level or product_heading:
                    skip_level = None
        if skip_level is not None:
            continue
        filtered = _filter_node(child)
        if filtered is not None:
            kept.append(filtered)
    flush_inline()
    node.children = kept
    return node


def _policy_only(source_text, source_heading, filtered):
    # 原文货号/字段名及保留下来的材质、特征保护商品正文；政策里的 dress 等泛称不算详情。
    faq_page = FAQ_TITLE_PATTERN.search(source_text.strip()) is not None
    if PRODUCT_FIELD_PATTERN.search(source_text) or not (POLICY_PATTERN.search(source_text) or faq_page):
        return False
    remaining = _normalized(_text(filtered)).strip()
    if PRODUCT_INFO_PATTERN.search(remaining):
        return False
    if faq_page:
        return True
    if source_heading is not None and _policy_heading(source_heading[1]):
        return True
    lines = [line.strip() for line in remaining.splitlines() if line.strip()]
    return bool(lines) and all(GENERIC_SERVICE_PATTERN.fullmatch(line) for line in lines)


def _block_key(node):
    # 行内加粗、缩进和实体写法不同不算不同段落；图片地址参与比较，避免误合并不同图片。
    text = re.sub(r'\s+', ' ', _normalized(_text(node))).strip().casefold()
    images = []

    def visit(current):
        if isinstance(current, _Node):
            if current.tag == 'img':
                images.extend(value for name, value in current.attrs if name == 'src')
            for child in current.children:
                visit(child)

    visit(node)
    if not text and not images:
        return None
    kind = 'heading' if re.fullmatch(r'h[1-6]', node.tag) else 'body'
    return kind, text, tuple(images)


def _deduplicate(root):
    seen_paragraphs = set()

    def visit(node):
        # 表格内部相同列值或行值必须保留；整张重复表格仍可由其父容器去重。
        if node.tag == 'table':
            return
        kept, seen_siblings = [], set()
        for child in node.children:
            if not isinstance(child, _Node):
                kept.append(child)
                continue
            key = _block_key(child) if _is_block(child) else None
            if key is not None and key in seen_siblings:
                continue
            if key is not None:
                seen_siblings.add(key)
            if (key is not None and child.tag not in TABLE_TAGS
                    and _is_block(child) and not any(_is_block(item) for item in child.children)):
                if key in seen_paragraphs:
                    continue
                seen_paragraphs.add(key)
            visit(child)
            kept.append(child)
        node.children = kept

    visit(root)


def _render(node):
    if isinstance(node, _Text):
        return escape(node.value, quote=False)
    children = ''.join(_render(child) for child in node.children)
    # article 是合法 HTML 标签，但也在零残留清单里：去掉容器，保留商品正文。
    if not node.tag or KEYWORD_PATTERN.search(node.tag):
        return children
    attrs = [(name, value) for name, value in node.attrs
             if value is not None and not POLICY_PATTERN.search(_normalized(value))
             and not KEYWORD_PATTERN.search(name)]
    if node.tag == 'img' and not any(name == 'src' and value for name, value in attrs):
        return ''
    if node.tag in VOID_TAGS:
        return '<' + node.tag + ''.join(f' {name}="{escape(value, quote=True)}"'
                                       for name, value in attrs) + '>'
    if node.tag not in TABLE_TAGS:
        visible = unescape(re.sub(r'<[^>]*>', '', children)).strip()
        if not visible and not re.search(r'<(?:img|table|colgroup|thead|tbody|tfoot|tr|td|th)\b', children):
            return ''
    attributes = ''.join(f' {name}="{escape(value, quote=True)}"' for name, value in attrs)
    return f'<{node.tag}{attributes}>' + children + (f'</{node.tag}>' if node.closed else '')


def strip_description_policy(html, *, clear_policy_only=True):
    """编号局部删除，政策按段落删除；合并重复块，并在原始信息尚存时识别纯政策页。"""
    if not html:
        return html
    parser = _DescriptionTree()
    parser.feed(html)
    parser.close()
    _drop_hidden_nodes(parser.root)
    source_text = _normalized(_policy_text(parser.root))
    source_heading = _leading_heading(parser.root)
    _remove_identifiers(parser.root)
    _split_mixed_paragraphs(parser.root)
    filtered = _filter_node(parser.root)
    if filtered is not None:
        if clear_policy_only and _policy_only(source_text, source_heading, filtered):
            return ''
        _deduplicate(filtered)
    return _render(filtered).strip() if filtered is not None else ''


def scan_description_keywords(html):
    """逐项返回零残留清单的计数，兼查 HTML 属性和跨行内标签的正文。"""
    parser = _DescriptionTree()
    parser.feed(str(html or ''))
    parser.close()
    raw, text = _normalized(str(html or '')), _normalized(_text(parser.root))
    return {term: max(len(pattern.findall(raw)), len(pattern.findall(text)))
            for term, pattern in KEYWORD_PATTERNS.items()}
