"""商品描述的统一清洗规则，阶段二落盘及原始商品解析共用。"""
import re
from html import escape
from html.parser import HTMLParser


# 清空规则：元素子树文本命中任一条，就清空该元素内容（保留标签本身）；
# 不在任何元素内的裸文本命中则直接删除该行。
# - made in：只认元素开头（允许前置符号与空白），如 <li>• Made in Poland</li>；
#   句中的 “This dress is made in Italy” 属于正常描述，不删。
# - sku：前后不接字母，命中 SKU、SKU:123、SKU#1、SKU123，不命中 skus。
MADE_HEAD_PATTERN = re.compile(r'^[\W_]*made\s+in\b', re.IGNORECASE)
SKU_PATTERN = re.compile(r'(?<![a-z])sku(?![a-z])', re.IGNORECASE)
REMOVED_TEXT_PATTERNS = (MADE_HEAD_PATTERN, SKU_PATTERN)

# 句子级规则：以 made in 开头的一句整句删除，用于段尾的 “... Made in the USA with quality you can trust.”
# 句子起点限定为文本开头或 . ! ? 之后，避免误删 “This dress is made in Italy” 这类句中描述。
MADE_SENTENCE_PATTERN = re.compile(
    r'(?:^|(?<=[.!?]))[ \t]*made\s+in\b[^.!?\n]*[.!?]?',
    re.IGNORECASE,
)


# 表格被整段删除后，描述里指向它的句子与纯标题会变成悬空内容，这里一并清掉。
# 只在该条描述确实删过 table 时启用，避免误伤正文里的普通 “table / chart” 用词。
TABLE_REF_PATTERN = re.compile(
    r'\b(?:size\s+)?(?:table|chart)\s+(?:below|above)\b'
    r'|\bsee\s+(?:the\s+)?(?:size\s+)?(?:table|chart)\b'
    r'|\brefer\s+to\s+(?:the\s+)?(?:size\s+)?(?:table|chart)\b'
    r'|见下(?:表|图|方表格)|如下表',
    re.IGNORECASE,
)
SIZE_HEADING_PATTERN = re.compile(
    r'^(?:(?:size|sizing)\s*(?:guide|chart|table)|measurements?(?:\s*(?:guide|chart|table))?'
    r'|尺码(?:表|对照表|指南|说明)?|尺寸(?:表|对照表)?)[:：]?$',
    re.IGNORECASE,
)


def _drop_table_refs(text):
    """删除指向表格的句子，保留同段其他句子与原有空白。"""
    if not text:
        return text
    lowered = text.casefold()
    if not any(token in lowered for token in ('table', 'chart', '下表', '见下')):
        return text
    sentences = re.findall(r'[^.!?\n]*(?:[.!?]+|$)', text)
    kept = [sent for sent in sentences if not TABLE_REF_PATTERN.search(sent)]
    return ''.join(kept)


class _TableRefCleaner(HTMLParser):
    """二次清理：删掉指向已删除表格的句子，以及内容只剩尺码表标题的元素。"""

    block_tags = {'p', 'div', 'li', 'td', 'th', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}

    def __init__(self):
        super().__init__(convert_charrefs=False)  # 文本已由上一轮转义过，这里原样透传
        self.parts = []
        self.frames = []

    def _target(self):
        return self.frames[-1]['parts'] if self.frames else self.parts

    def _flush(self, frame):
        text = re.sub(r'\s+', ' ', ''.join(frame['text'])).strip()
        if frame['tag'] in self.block_tags and text and SIZE_HEADING_PATTERN.match(text):
            return  # 只剩标题文字：整个元素丢弃
        self._target().extend(frame['parts'])

    @staticmethod
    def _render_attrs(attrs):
        pieces = []
        for name, value in attrs:
            if value is None:
                continue
            pieces.append(f' {name}="{escape(value, quote=True)}"')
        return ''.join(pieces)

    def handle_starttag(self, tag, attrs):
        if tag in ('br', 'hr', 'wbr'):
            self._target().append(f'<{tag}>')
            return
        if tag in ('img', 'source', 'track', 'embed', 'param', 'meta', 'link', 'base', 'input'):
            self._target().append(f'<{tag}{self._render_attrs(attrs)}>')
            return
        self.frames.append({'tag': tag, 'parts': [f'<{tag}{self._render_attrs(attrs)}>'], 'text': []})

    def handle_startendtag(self, tag, attrs):
        self._target().append(f'<{tag}{self._render_attrs(attrs)}>')

    def handle_endtag(self, tag):
        index = None
        for position in range(len(self.frames) - 1, -1, -1):
            if self.frames[position]['tag'] == tag:
                index = position
                break
        if index is None:
            self._target().append(f'</{tag}>')
            return
        while len(self.frames) > index:
            frame = self.frames.pop()
            if frame['tag'] == tag:
                frame['parts'].append(f'</{tag}>')
            self._flush(frame)

    def handle_data(self, data):
        data = _drop_table_refs(data)
        if not data:
            return
        self._target().append(data)
        if self.frames:
            self.frames[-1]['text'].append(data)

    def get_html(self):
        while self.frames:
            self._flush(self.frames.pop())
        return ''.join(self.parts).strip()


def strip_table_references(html):
    """表格删除后清理悬空引用；没有表格的调用方不会走到这里。"""
    cleaner = _TableRefCleaner()
    cleaner.feed(html)
    cleaner.close()
    return cleaner.get_html()


def strip_made_sentences(text):
    """删除以 made in 开头的句子；只删句子，保留同段其余内容。"""
    if 'made' not in text.casefold():
        return text
    cleaned = MADE_SENTENCE_PATTERN.sub('', text)
    if cleaned == text:
        return text
    if MADE_SENTENCE_PATTERN.match(text):  # 句首命中时去掉遗留的前导空白
        cleaned = cleaned.lstrip(' \t')
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
    return cleaned if cleaned.strip() else ''


class _Element:
    """未闭合元素：自己收集输出片段与子树文本，闭合时再决定保留还是丢弃。"""

    __slots__ = ('tag', 'parts', 'text', 'closed', 'has_payload')

    def __init__(self, tag):
        self.tag = tag
        self.parts = []      # 该元素产出的 HTML 片段（含子元素）
        self.text = []       # 该元素子树内的原始文本，供清空规则判定
        self.closed = False  # 是否在源码里显式闭合，决定清空后是否补结束标签
        self.has_payload = False  # 是否有真正保留的内容（文字或图片）


class CleanBodyHtmlParser(HTMLParser):
    # 媒体容器连同内部资源和兜底文字一起删除，避免留下播放器碎片。
    # script/style/template/noscript 是代码或不可见内容，留着会把 URL、id 选择器写进描述；
    # svg 与图片同属媒体资源，属性剥离后只剩空壳，默认一并删除；
    # table 多为尺码表 / 参数表，平台详情页不识别表格结构，且 cm 与 in 双语数值会把描述撑长，
    # 因此默认连标签带内容整段删除（含嵌套表格）；开启 keep_tables 时把 table 当作普通标签保留。
    removed_content_tags = {
        'a', 'video', 'iframe', 'object', 'script', 'style', 'template', 'noscript', 'svg', 'table',
    }
    # 没有正文意义的标签直接丢弃（meta/link/base/input 等出现在描述里只是残留）
    removed_void_tags = {
        'img', 'source', 'track', 'embed', 'param',
        'meta', 'link', 'base', 'input', 'area', 'col',
    }
    void_tags = {
        'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr',
    }
    image_attrs = {'src'}
    # 表格结构容器标签：只做结构、不承载正文，空内容时也不清理（保留 colgroup/thead/tbody/tr 等骨架）。
    table_structure_tags = {'table', 'colgroup', 'thead', 'tbody', 'tfoot', 'tr'}

    def __init__(self, *, keep_images=False, keep_tables=False):
        super().__init__(convert_charrefs=True)
        self.keep_images = bool(keep_images)
        self.keep_tables = bool(keep_tables)
        # keep_tables 开启时把 table 从「整段删除」名单里摘出，当作普通标签走常规保留流程。
        self.removed_content_tags = set(self.removed_content_tags)
        if self.keep_tables:
            self.removed_content_tags.discard('table')
        self.parts = []       # 根层输出
        self.frames = []      # 未闭合元素栈：闭合时才知道子树文本是否命中删除规则
        self.skip_stack = []
        self.removed_tables = 0  # 删掉的 table 数量，供二次清理判断是否需要删悬空引用
        self.table_depth = 0     # 当前处于 table 子树内的嵌套层数，>0 时标签保留原始属性

    @staticmethod
    def _render_attrs(attrs):
        # 只保留行列合并相关的属性（colspan/rowspan/span），其余 style/class/width 等一律丢弃，
        # 让表格保持干净的合并结构而不带冗余 CSS。span 是 col 的列数定义属性，
        # 保留后 <col span="4"> 才能如实表达 colgroup 的列数。
        pieces = []
        for name, value in attrs:
            if name in ('colspan', 'rowspan', 'span') and value is not None:
                pieces.append(f' {name}="{escape(value, quote=True)}"')
        return ''.join(pieces)

    # ---- 缓冲区 ----
    def _current_parts(self):
        # 输出写到最内层未闭合元素；没有未闭合元素时写根层
        return self.frames[-1].parts if self.frames else self.parts

    def _current_text(self):
        # 子树文本先只累积到最内层，闭合后由 _absorb 上抛给祖先
        return self.frames[-1].text if self.frames else None

    def _absorb(self, frame):
        # 命中规则或整段内容都被清空：只保留元素标签，内容不保留、文本也不上抛，
        # 避免外层被连带清空。表格结构容器（colgroup/tr 等）无正文也照常保留骨架。
        is_table_structure = frame.tag in self.table_structure_tags
        if not is_table_structure and (self._should_drop(frame) or not frame.has_payload):
            kept = list(frame.parts[:1])
            if frame.closed:
                kept.append(f'</{frame.tag}>')
            self._current_parts().extend(kept)
            return
        self._current_parts().extend(frame.parts)
        if self.frames:
            self.frames[-1].has_payload = True
        text = self._current_text()
        if text is not None:
            text.extend(frame.text)

    @staticmethod
    def _matches_text(text):
        if not text:
            return False
        # 片段之间补空格再合并空白，避免 <b>made</b><i>in</i> 被粘成 madein
        text = re.sub(r'\s+', ' ', text).strip()
        return bool(text) and any(pattern.search(text) for pattern in REMOVED_TEXT_PATTERNS)

    @classmethod
    def _should_drop(cls, frame):
        # 命中即清空元素内容（保留标签）；判据都用元素原文，避免被句子级删除影响
        if not frame.text:
            return False
        text = re.sub(r'\s+', ' ', ' '.join(frame.text)).strip()
        if not text:
            return False
        if SKU_PATTERN.search(text):
            return True
        # made in 只在整个元素就是这一句时清空，避免连带删掉同段其他句子
        return bool(MADE_HEAD_PATTERN.search(text)) and not strip_made_sentences(text).strip()

    # ---- 解析回调 ----
    def handle_starttag(self, tag, attrs):
        if tag in self.removed_content_tags:
            if tag == 'table':
                self.removed_tables += 1
            self.skip_stack.append(tag)
            return
        if tag == 'img' and self.keep_images:
            if not self.skip_stack:
                # 图片仅保留 src；不将懒加载属性转换为 src。
                attributes = ''.join(f' {name}="{escape(value, quote=True)}"'
                                     for name, value in attrs
                                     if name in self.image_attrs and value is not None)
                self._current_parts().append(f'<img{attributes}>')
                if self.frames:
                    self.frames[-1].has_payload = True
            return
        if self.skip_stack:
            return
        # table 子树内：保留结构标签，但只保留 colspan/rowspan 行列合并属性，
        # 其余 style/class/width/border 等一律丢弃；进入/离开 table 时维护深度。
        in_table = self.table_depth > 0
        if tag == 'table':
            self.table_depth += 1
            in_table = True
        if in_table:
            # 结构标签保留，但只保留 colspan/rowspan/span 行列合并与列数属性。
            if tag in self.void_tags:
                self._current_parts().append(f'<{tag}{self._render_attrs(attrs)}>')
                return
            frame = _Element(tag)
            frame.parts.append(f'<{tag}{self._render_attrs(attrs)}>')
            self.frames.append(frame)
            return
        if tag in self.removed_void_tags:
            return
        # 只保留标签名称，统一去掉 style、class、id 等属性。
        if tag in self.void_tags:  # br / hr / wbr 等自闭合标签不产生元素帧
            self._current_parts().append(f'<{tag}>')
            return
        # 开始标签写进元素帧自己的片段：命中删除规则时才能连开标签一起丢掉
        frame = _Element(tag)
        frame.parts.append(f'<{tag}>')
        self.frames.append(frame)

    def handle_endtag(self, tag):
        if tag in self.removed_content_tags:
            # 内部容器未闭合时，外层的闭合标签也能结束整段删除。
            for index in range(len(self.skip_stack) - 1, -1, -1):
                if self.skip_stack[index] == tag:
                    del self.skip_stack[index:]
                    break
            return
        if self.skip_stack or tag in self.void_tags:
            return
        # table 子树内：闭合 table 时回退深度（在取 frame 之前处理，避免误判）。
        if tag == 'table' and self.table_depth > 0:
            self.table_depth -= 1
        index = None
        for position in range(len(self.frames) - 1, -1, -1):
            if self.frames[position].tag == tag:
                index = position
                break
        if index is None:
            # 没有配对的开始标签：保持原有行为，原样补上结束标签
            self._current_parts().append(f'</{tag}>')
            return
        # 先收掉内层未闭合元素（不补结束标签，与改造前输出一致），再关闭本元素
        while len(self.frames) > index:
            frame = self.frames.pop()
            if frame.tag == tag:
                frame.parts.append(f'</{tag}>')
                frame.closed = True
            self._absorb(frame)

    def handle_startendtag(self, tag, attrs):
        if tag == 'img' and self.keep_images:
            self.handle_starttag(tag, attrs)
            return
        if self.skip_stack:
            return
        # table 子树内的自闭合结构标签（如 <col ... />）保留属性。
        if self.table_depth > 0:
            self._current_parts().append(f'<{tag}{self._render_attrs(attrs)}>')
            return
        if tag not in self.removed_content_tags | self.removed_void_tags:
            self._current_parts().append(f'<{tag}>')

    def handle_data(self, data):
        if self.skip_stack:
            return
        # 非 BMP 字符（含部分 emoji）无法稳定写入平台，直接丢弃
        data = ''.join(ch for ch in data if ord(ch) <= 0xFFFF)
        if not data:
            return
        text = self._current_text()
        if text is not None:
            text.append(data)  # 元素级规则用原文判定，先入缓冲
        # 句子级：删掉以 made in 开头的整句，同段其余文字保留
        data = strip_made_sentences(data)
        if not data:  # 整段被句子规则删空
            return
        if not self.frames:
            # 裸文本（不在任何元素内）：没有标签可清空，命中规则的行直接删除，
            # 同一文本节点内的其他行保留。
            lines = data.splitlines()
            kept = [line for line in lines if not self._matches_text(line)]
            if len(kept) != len(lines):
                if not any(line.strip() for line in kept):
                    return
                data = '\n'.join(kept)
        self._current_parts().append(escape(data, quote=False))
        if data.strip() and self.frames:  # 纯换行/空白不算内容
            self.frames[-1].has_payload = True

    def get_html(self):
        # 未闭合元素按原样展开（不补结束标签），保持与改造前一致的输出
        while self.frames:
            self._absorb(self.frames.pop())
        # 不再清理空成对标签：清空规则留下的 <li></li>、<p></p> 要保留，
        # 否则二次清洗会把它们当成空壳删掉，导致结果不幂等。
        return ''.join(self.parts).strip()

def clean_body_html(body_html, *, keep_images=False, keep_tables=False):
    """默认删除图片与表格；keep_images 开启仅保留 img 的 src，keep_tables 开启则保留 table 表格。
    链接、视频及其他清洗规则始终生效。"""
    if not body_html:
        return ''
    parser = CleanBodyHtmlParser(keep_images=keep_images, keep_tables=keep_tables)
    parser.feed(str(body_html))
    parser.close()
    html = parser.get_html()
    if parser.removed_tables:  # 删过表格才清理悬空引用，普通描述完全不受影响
        without_refs = strip_table_references(html)
        if without_refs != html:
            # 引用文字被删后可能留下嵌套空壳；在本次清洗内收尾，
            # 避免调用方必须再次清洗才能得到稳定结果。
            parser = CleanBodyHtmlParser(keep_images=keep_images, keep_tables=keep_tables)
            parser.feed(without_refs)
            parser.close()
            return parser.get_html()
    return html
