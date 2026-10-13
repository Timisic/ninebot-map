import json
import unittest
from pathlib import Path
import tempfile

from nbmap.place_names import PlaceNameRejected, PlaceNameUnavailable, PlaceNames

RIDE = 'r_' + 'a' * 24
OTHER = 'r_' + 'b' * 24
UPDATED = '2026-02-01T00:00:00Z'
MAX_NAMES = 25000


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def dataset(**extra):
    return dumps({'format': 'ride-dataset', 'generated_at': UPDATED, 'updated_at': UPDATED, **extra})


def public(**annotations):
    body = {'format': 'public-ride-map', 'updated_at': UPDATED}
    if annotations:
        body['place_annotations'] = annotations
    return dumps(body)


def request(ride_ids, name):
    return dumps({'name': name, 'rideIds': ride_ids})


class PlaceNameTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def open(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        return path, PlaceNames.open(path)

    def test_ledger_path_follows_the_dataset_passed_to_the_server(self):
        for relative in ('prepared/generation/dataset.json', 'prepared/dataset.json', 'data/dataset.json', 'other/dataset.json'):
            path, names = self.open(relative)
            path.write_bytes(dataset())
            names.save(request([RIDE], '球馆'), path.read_bytes())
        self.assertTrue((self.root / 'prepared/place-names.json').is_file())
        self.assertFalse((self.root / 'prepared/generation/place-names.json').exists())
        self.assertTrue((self.root / 'data/place-names.json').is_file())
        self.assertTrue((self.root / 'other/place-names.json').is_file())

    def test_saved_name_is_projected_without_rewriting_the_dataset(self):
        path, names = self.open('data/dataset.json')
        raw = dataset()
        path.write_bytes(raw)
        body = request([RIDE], '球馆🏸')
        response = json.loads(names.save(body, raw))
        self.assertEqual(response['labels'][RIDE], '球馆🏸')
        served = names.overlay(raw)
        again = names.overlay(raw)
        self.assertEqual(again.body, served.body)
        self.assertEqual(again.etag, served.etag)
        self.assertIn('球馆🏸'.encode(), served.body)
        self.assertIn(b'\xf0\x9f\x8f\xb8', served.body)
        self.assertNotIn(b'\\u', served.body)
        parsed = json.loads(served.body)
        self.assertEqual(parsed['place_annotations']['labels'][RIDE], '球馆🏸')
        self.assertNotIn('merges', parsed['place_annotations'])
        self.assertEqual(parsed['updated_at'], UPDATED)
        self.assertEqual(path.read_bytes(), raw)
        ledger = json.loads((self.root / 'data/place-names.json').read_text())
        self.assertEqual(ledger, {'cleared': [], 'overrides': {RIDE: '球馆🏸'}})

    def test_same_body_does_not_replace_the_ledger(self):
        path, names = self.open('data/dataset.json')
        raw = dataset()
        body = request([OTHER, RIDE], '球馆🏸')
        names.save(body, raw)
        ledger = self.root / 'data/place-names.json'
        before = ledger.stat()
        names.save(request([RIDE, OTHER], '球馆🏸'), raw)
        after = ledger.stat()
        self.assertEqual(before.st_ino, after.st_ino)
        self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)
        self.assertEqual(ledger.read_bytes(), dumps({'cleared': [], 'overrides': {RIDE: '球馆🏸', OTHER: '球馆🏸'}}))

    def test_clear_writes_a_tombstone_that_a_new_publisher_label_does_not_restore(self):
        path, names = self.open('data/dataset.json')
        raw = public(labels={RIDE: '旧名', OTHER: '公园'}, merges=[{'anchorId': RIDE, 'memberIds': [RIDE, OTHER]}])
        path.write_bytes(raw)
        names.save(request([RIDE], None), raw)
        ledger = json.loads((self.root / 'data/place-names.json').read_text())
        self.assertEqual(ledger['cleared'], [RIDE])
        self.assertNotIn(RIDE, ledger['overrides'])
        hidden = json.loads(names.overlay(raw).body)
        self.assertNotIn(RIDE, hidden['place_annotations']['labels'])
        self.assertEqual(hidden['place_annotations']['labels'][OTHER], '公园')
        self.assertEqual(hidden['place_annotations']['merges'], [{'anchorId': RIDE, 'memberIds': [RIDE, OTHER]}])
        self.assertEqual(path.read_bytes(), raw)
        revised = dumps({'format': 'public-ride-map', 'updated_at': '2026-03-01T00:00:00Z', 'place_annotations': {'labels': {RIDE: '新名', OTHER: '公园'}, 'merges': []}})
        restored = json.loads(names.overlay(revised).body)
        self.assertNotIn(RIDE, restored['place_annotations']['labels'])
        self.assertEqual(restored['place_annotations']['labels'][OTHER], '公园')
        self.assertEqual(restored['updated_at'], '2026-03-01T00:00:00Z')
        self.assertEqual(path.read_bytes(), raw)

    def test_projection_over_the_cap_leaves_the_file_unchanged(self):
        path, names = self.open('data/dataset.json')
        labels = {f'r_{index:024x}': '馆' for index in range(MAX_NAMES)}
        raw = public(labels=labels)
        path.write_bytes(raw)
        names.save(request([f'r_{0:024x}'], '馆'), raw)
        ledger = self.root / 'data/place-names.json'
        before = ledger.read_bytes()
        stat = ledger.stat()
        extra = f'r_{MAX_NAMES:024x}'
        with self.assertRaises(PlaceNameRejected) as caught:
            names.save(request([extra], '新馆'), raw)
        self.assertEqual(caught.exception.status, 413)
        self.assertEqual(ledger.read_bytes(), before)
        self.assertEqual(ledger.stat().st_ino, stat.st_ino)
        self.assertNotIn(extra, json.loads(names.overlay(raw).body)['place_annotations']['labels'])

    def test_empty_name_is_rejected_and_a_corrupt_ledger_is_not_replaced(self):
        path, names = self.open('data/dataset.json')
        raw = dataset()
        with self.assertRaises(PlaceNameRejected) as caught:
            names.save(request([RIDE], ''), raw)
        self.assertEqual(caught.exception.status, 400)
        self.assertFalse((self.root / 'data/place-names.json').exists())
        with self.assertRaises(PlaceNameRejected):
            names.save(request([RIDE], ' 球馆'), raw)
        ledger = self.root / 'data/place-names.json'
        ledger.write_bytes(b'{')
        before = ledger.read_bytes()
        served = json.loads(names.overlay(public(labels={RIDE: '发布名'})).body)
        self.assertEqual(served['place_annotations']['labels'][RIDE], '发布名')
        with self.assertRaises(PlaceNameUnavailable):
            names.save(request([RIDE], '球馆'), raw)
        self.assertEqual(ledger.read_bytes(), before)

    def test_ride_dataset_annotations_are_not_the_base_and_public_merges_are_copied(self):
        path, names = self.open('maps/dataset.json')
        raw = dataset(place_annotations={'labels': {RIDE: '原始名'}, 'merges': [{'anchorId': RIDE, 'memberIds': [RIDE, OTHER]}]})
        path.write_bytes(raw)
        served = json.loads(names.overlay(raw).body)
        self.assertEqual(served['place_annotations'], {'labels': {}})
        self.assertEqual(path.read_bytes(), raw)
        names.save(request(['place-103'], '列表外'), raw)
        renamed = json.loads(names.overlay(raw).body)
        self.assertEqual(renamed['place_annotations']['labels'], {'place-103': '列表外'})
        self.assertNotIn('merges', renamed['place_annotations'])
        omitted = json.loads(names.overlay(public(labels={RIDE: '馆'})).body)
        self.assertEqual(omitted['place_annotations']['merges'], [])
        self.assertEqual(omitted['place_annotations']['labels']['place-103'], '列表外')
        legacy = json.loads(names.overlay(dumps({'format': 'public-ride-map', 'updated_at': UPDATED})).body)
        self.assertEqual(set(legacy['place_annotations']), {'labels'})


if __name__ == '__main__':
    unittest.main()
