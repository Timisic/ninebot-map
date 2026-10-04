"""Private atomic persistence. Raw responses remain separate from derived exports."""
import csv
import io
import json
import os
import tempfile
import fcntl
from contextlib import contextmanager
from pathlib import Path


def private_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


@contextmanager
def sync_lock(root):
    """One writer per local archive directory; the OS releases locks after crashes."""
    path = private_dir(root) / 'sync.lock'
    with path.open('a') as stream:
        path.chmod(0o600)
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('另一个同步或配置任务正在运行，请稍后重试。') from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def write_text(path, text):
    path = Path(path)
    private_dir(path.parent)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".writing-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_csv(path, rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        # Neutralize spreadsheet formulas in untrusted textual fields.
        writer.writerow({k: ("'" + v if isinstance(v, str) and v.lstrip().startswith(
            ("=", "+", "-", "@")) else v) for k, v in row.items()})
    write_text(path, "\ufeff" + stream.getvalue())
