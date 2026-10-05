#!/usr/bin/env python3
"""Forced-command receiver. Its only input is one allowlisted public map JSON."""
import argparse
import fcntl
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nbmap.public_map import publish_dataset
from nbmap.map_server import MAX_BYTES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', type=Path, required=True)
    args = parser.parse_args()
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('oversized')
    data = json.loads(raw)
    args.target.parent.mkdir(parents=True, exist_ok=True)
    with (args.target.parent.parent / '.publish-map.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        publish_dataset(data, args.target)
    print('Published public map ' + hashlib.sha256(args.target.read_bytes()).hexdigest())


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Public map rejected; previous data retained.', file=sys.stderr)
        raise SystemExit(1)
