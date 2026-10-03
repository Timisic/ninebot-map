"""Private atomic persistence. Raw responses remain separate from derived exports."""
import csv
import io
import json
import os
import tempfile
from pathlib import Path


def private_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


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
