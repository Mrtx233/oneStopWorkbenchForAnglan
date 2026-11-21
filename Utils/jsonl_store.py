"""Read editable JSONL objects while retaining malformed lines for safe saves."""
import hashlib
import json
import os
from pathlib import Path
import tempfile


class JsonlRecords(list):
    """Only valid objects are editable; other source lines stay in the file layout."""

    def __init__(self):
        super().__init__()
        self.invalid_lines = []
        self.backup_path = None
        self._layout = []
        self._source_digest = None


def _read_source(path):
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _digest(data):
    return None if data is None else hashlib.sha256(data).digest()


def load_records(path):
    records = JsonlRecords()
    data = _read_source(Path(path))
    records._source_digest = _digest(data)
    for line_no, raw in enumerate((data or b'').splitlines(keepends=True), 1):
        try:
            text = raw.decode('utf-8-sig')
            if not text.strip():
                records._layout.append(raw)
                continue
            record = json.loads(text)
            if not isinstance(record, dict):
                raise ValueError('JSONL record must be an object')
        except (UnicodeDecodeError, ValueError):
            records.invalid_lines.append(line_no)
            records._layout.append(raw)
        else:
            records.append(record)
            records._layout.append(record)
    return records


def _serialize(records):
    active = {id(record) for record in records}
    written = set()
    lines = []

    def append(line):
        # A damaged final line may have no newline; keep appended records on their own line.
        if lines and not lines[-1].endswith((b'\r', b'\n')):
            lines.append(b'\n')
        lines.append(line)

    def encode(record):
        if not isinstance(record, dict):
            raise ValueError('链接记录必须是 JSON 对象')
        return (json.dumps(record, ensure_ascii=False) + '\n').encode('utf-8')

    for item in records._layout:
        if isinstance(item, bytes):
            append(item)
        elif id(item) in active:
            append(encode(item))
            written.add(id(item))
    for record in records:
        if id(record) not in written:
            append(encode(record))
    return b''.join(lines)


def _backup_source(path, data):
    index = 1
    while True:
        suffix = '.bak' if index == 1 else f'.bak{index}'
        backup = path.with_name(path.name + suffix)
        try:
            stream = backup.open('xb')
        except FileExistsError:
            index += 1
            continue
        try:
            with stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            backup.unlink(missing_ok=True)
            raise
        return backup


def _check_source(path, records):
    current = _read_source(path)
    if _digest(current) != records._source_digest:
        raise RuntimeError('链接库文件已被其他程序修改，请重新打开链接库后再保存')
    return current


def save_records(path, records):
    """Preserve opaque lines, back up damaged input, and atomically replace the file."""
    path = Path(path)
    data = _serialize(records)  # Serialization errors must leave the source untouched.
    original = _check_source(path, records)
    path.parent.mkdir(parents=True, exist_ok=True)
    if records.invalid_lines and records.backup_path is None and original is not None:
        records.backup_path = _backup_source(path, original)
    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _check_source(path, records)
        os.replace(temporary, path)
        records._source_digest = _digest(data)
    finally:
        temporary.unlink(missing_ok=True)
    return records.backup_path
