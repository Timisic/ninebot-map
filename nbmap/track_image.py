"""Render only sampled tracks to a PNG, without a basemap or geographic metadata."""
import math
from pathlib import Path
from PIL import Image, ImageDraw
from .dataset import validate_dataset


def render_tracks(dataset, path, width=1200, height=900):
    validate_dataset(dataset)
    points = [p for t in dataset['tracks'] for p in t['points']]
    scale, margin = 3, 45
    image = Image.new('RGB', (width * scale, height * scale), '#f8faf8')
    if points:
        lon0 = sum(p['longitude'] for p in points) / len(points)
        lat0 = sum(p['latitude'] for p in points) / len(points)
        def project(p):
            return ((p['longitude'] - lon0) * 111320 * math.cos(math.radians(lat0)),
                    (p['latitude'] - lat0) * 111320)
        xy = [project(p) for p in points]
        minx, maxx = min(p[0] for p in xy), max(p[0] for p in xy)
        miny, maxy = min(p[1] for p in xy), max(p[1] for p in xy)
        factor = min((width - 2 * margin) / max(maxx - minx, 1), (height - 2 * margin) / max(maxy - miny, 1))
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        def pixel(p):
            x, y = project(p)
            return ((width / 2 + (x - cx) * factor) * scale, (height / 2 - (y - cy) * factor) * scale)
        draw = ImageDraw.Draw(image, 'RGBA')
        for track in dataset['tracks']:
            for first, second in zip(track['points'], track['points'][1:]):
                a, b = project(first), project(second)
                if math.hypot(a[0] - b[0], a[1] - b[1]) <= 1000:
                    draw.line([pixel(first), pixel(second)], fill=(36, 124, 91, 105), width=2 * scale)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.resize((width, height), Image.Resampling.LANCZOS).save(path, format='PNG', optimize=True)
    return path
