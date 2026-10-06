#!/usr/bin/env python3
"""Forced-command receiver. Its only input is one allowlisted public map JSON."""
import argparse
import fcntl
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nbmap.public_map import publish_dataset, validate_public
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
        validate_public(data)
        requested = data['updated_at']
        status, reason = 'published', 'accepted'
        before = args.target.read_bytes() if args.target.exists() else None
        if before is not None:
            current = validate_public(json.loads(before))
            if datetime.fromisoformat(requested.replace('Z', '+00:00')) < datetime.fromisoformat(current['updated_at'].replace('Z', '+00:00')):
                status, reason = 'skipped_older', 'current_is_newer'
            else:
                publish_dataset(data, args.target)
                if args.target.read_bytes() == before:
                    status, reason = 'unchanged', 'identical_bytes'
        else:
            publish_dataset(data, args.target)
        active = args.target.read_bytes()
        receipt = {'status': status, 'reason': reason, 'sha256': hashlib.sha256(active).hexdigest(),
                   'updated_at': json.loads(active)['updated_at'], 'requested_updated_at': requested}
        print('Public map receipt: ' + json.dumps(receipt, sort_keys=True))



if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Public map rejected; previous data retained.', file=sys.stderr)
        raise SystemExit(1)
