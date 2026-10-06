import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nbmap.cloud import worker


class PublicUpdateWorkerTests(unittest.TestCase):
    def test_public_collection_requires_all_approved_outputs(self):
        settings = {'enabled': True, 'site': {'host': 'example.invalid'},
                    'publish_repos': [{'repo': 'owner/map'}, {'repo': 'owner/owner'}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            variants = [dict(settings, site=None), dict(settings, enabled=False),
                        dict(settings, publish_repos=[{'repo': 'owner/map'}]),
                        dict(settings, publish_repos=[{'repo': 'owner/map'}, {'repo': 'owner/map'}])]
            for incomplete in variants:
                (root / 'sync-settings.json').write_text(json.dumps(incomplete))
                with patch.dict('os.environ', {'SYNC_PUBLIC_REQUEST_ID': '12345678-1234-4123-8123-123456789012',
                                             'SYNC_FORCE': 'true', 'SYNC_PUBLISH_ONLY': 'false'}, clear=True):
                    with self.assertRaisesRegex(ValueError, '网站和两个图片目标'):
                        worker(root)

    def test_public_request_cannot_republish_without_collecting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sync-settings.json').write_text('{}')
            for force, publish_only in [('false', 'false'), ('true', 'true')]:
                with patch.dict('os.environ', {'SYNC_PUBLIC_REQUEST_ID': '12345678-1234-4123-8123-123456789012',
                                             'SYNC_FORCE': force, 'SYNC_PUBLISH_ONLY': publish_only}, clear=True):
                    with self.assertRaisesRegex(ValueError, '必须执行采集'):
                        worker(root)

    def test_public_request_id_is_validated_before_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'sync-settings.json').write_text('{}')
            with patch.dict('os.environ', {'SYNC_PUBLIC_REQUEST_ID': 'arbitrary input'}, clear=True):
                with self.assertRaisesRegex(ValueError, '请求标识无效'):
                    worker(root)
