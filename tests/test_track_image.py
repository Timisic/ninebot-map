import copy
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops

from nbmap.track_image import render_tracks


class TrackImageTests(unittest.TestCase):
    def test_long_flat_routes_have_small_margin_on_all_four_sides(self):
        data = json.loads(Path('tests/fixtures/synthetic-map.json').read_text())
        for track in data['tracks']:
            for point in track['points']:
                point['latitude'] = 39.9
        with tempfile.TemporaryDirectory() as directory:
            path = render_tracks(data, Path(directory) / 'tracks.png')
            with Image.open(path) as image:
                bounds = ImageChops.difference(image, Image.new('RGB', image.size, '#f8faf8')).getbbox()
                self.assertIsNotNone(bounds)
                self.assertLess(image.height, 50)
                margins = [bounds[0], bounds[1], image.width - bounds[2], image.height - bounds[3]]
                self.assertTrue(all(10 <= value <= 17 for value in margins), margins)
                self.assertEqual(image.info, {})

    def test_empty_tracks_still_produce_valid_png_without_metadata(self):
        data = json.loads(Path('tests/fixtures/synthetic-map.json').read_text())
        data = copy.deepcopy(data)
        for ride in data['rides']:
            ride.update(track_kind='missing', source_point_count=0, map_status='insufficient_points')
        data['tracks'] = []
        data['summary'].update(map_ride_count=0, map_distance_m=0, map_point_count=0,
                               map_exclusions={'insufficient_points': len(data['rides'])})
        with tempfile.TemporaryDirectory() as directory:
            with Image.open(render_tracks(data, Path(directory) / 'empty.png')) as image:
                self.assertEqual(image.size, (1200, 900))
                self.assertEqual(image.info, {})
                self.assertEqual(len(image.getcolors(image.width * image.height)), 1)
