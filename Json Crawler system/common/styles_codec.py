"""款式字符串的对称转义、切分与组合；图片地址不参与属性转义。"""

RESERVED = "\\&#@"


def escape(value):
    text = "" if value is None else str(value)
    return "".join("\\" + ch if ch in RESERVED else ch for ch in text)


def unescape(text):
    result = []
    index = 0
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text) and text[index + 1] in RESERVED:
            index += 1
        result.append(text[index])
        index += 1
    return "".join(result)


def split(text, separator):
    """只切未转义的分隔符，保留转义直到属性值最终解码。"""
    parts, start, index = [], 0, 0
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text) and text[index + 1] in RESERVED:
            index += 2
            continue
        if text[index] == separator:
            parts.append(text[start:index])
            start = index + 1
        index += 1
    parts.append(text[start:])
    return parts


def partition_image(segment):
    # 图片前的 @ 是第一个未转义的 @；URL 本身可以再包含 @。
    parts = split(segment, "@")
    return (parts[0], "@", "@".join(parts[1:])) if len(parts) > 1 else (segment, "", "")


def decode_segment(segment):
    text, _, image = partition_image(segment)
    parts = text.rsplit("$", 2)
    options, sale, compare = parts if len(parts) == 3 else (text, "", "")
    values = [unescape(value) for value in split(options, "&")] if options else []
    return values, sale, compare, image


def encode_segment(values, sale, compare, image=""):
    segment = f"{'&'.join(escape(value) for value in values)}${sale}${compare}"
    return f"{segment}@{image}" if image else segment
