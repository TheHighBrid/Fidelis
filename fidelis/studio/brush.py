"""Validated normalized brush strokes, rasterized at native resolution in stripes."""
import math
import numpy as np

EDIT_FIELDS = ('skin', 'hair', 'fabric', 'protected', 'confidence')


def validate_strokes(strokes):
    if not isinstance(strokes, list) or len(strokes) > 100:
        raise ValueError('At most 100 strokes can be saved per edit')
    total = 0
    normalized = []
    for stroke in strokes:
        if not isinstance(stroke, dict) or set(stroke) != {'layer', 'mode', 'radius', 'hardness', 'opacity', 'points'}:
            raise ValueError('Invalid brush stroke fields')
        if stroke['layer'] not in EDIT_FIELDS[:-1] or stroke['mode'] not in ('paint', 'erase'):
            raise ValueError('Invalid brush layer or mode')
        for key in ('radius', 'hardness', 'opacity'):
            value = stroke[key]
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError('Brush values must be finite numbers')
        if not .0001 <= stroke['radius'] <= .5 or not 0 <= stroke['hardness'] <= 1 or not 0 <= stroke['opacity'] <= 1:
            raise ValueError('Brush values outside allowed range')
        points = stroke['points']
        if not isinstance(points, list) or not 1 <= len(points) <= 1000:
            raise ValueError('A stroke requires 1 to 1000 normalized points')
        total += len(points)
        if total > 4000:
            raise ValueError('Edit exceeds 4000 brush points')
        for point in points:
            if not isinstance(point, (list, tuple)) or len(point) != 2 or any(
                    isinstance(value, bool) or not isinstance(value, (int, float)) or
                    not math.isfinite(value) or not 0 <= value <= 1 for value in point):
                raise ValueError('Brush points must lie inside the normalized image')
        normalized.append({**stroke, 'points': [list(point) for point in points]})
    return normalized


def coverage(stroke, width, height, y0, y1):
    """Max capsule coverage: overlaps within one stroke do not multiply opacity."""
    result = np.zeros((y1 - y0, width), np.float32)
    radius = stroke['radius'] * min(width, height)
    points = [(x * width - .5, y * height - .5) for x, y in stroke['points']]
    pairs = list(zip(points, points[1:])) if len(points) > 1 else [(points[0], points[0])]
    for (ax, ay), (bx, by) in pairs:
        left = max(0, math.floor(min(ax, bx) - radius))
        right = min(width, math.ceil(max(ax, bx) + radius) + 1)
        top = max(y0, math.floor(min(ay, by) - radius))
        bottom = min(y1, math.ceil(max(ay, by) + radius) + 1)
        if right <= left or bottom <= top:
            continue
        yy, xx = np.ogrid[top:bottom, left:right]
        dx, dy = bx - ax, by - ay
        denominator = dx * dx + dy * dy
        t = np.clip(((xx - ax) * dx + (yy - ay) * dy) / max(denominator, 1e-12), 0, 1)
        distance = np.sqrt((xx - ax - t * dx) ** 2 + (yy - ay - t * dy) ** 2) / radius
        if stroke['hardness'] == 1:
            amount = (distance <= 1).astype(np.float32)
        else:
            amount = np.clip((1 - distance) / (1 - stroke['hardness']), 0, 1).astype(np.float32)
        region = result[top - y0:bottom - y0, left:right]
        np.maximum(region, amount * stroke['opacity'], out=region)
    return result


def apply_stripe(fields, strokes, width, height, y0, y1):
    """Mutate writable float32 stripe fields; protection is never implicitly erased."""
    for stroke in strokes:
        amount = coverage(stroke, width, height, y0, y1)
        target = fields[stroke['layer']]
        if stroke['mode'] == 'erase':
            target *= 1 - amount
        else:
            target += (1 - target) * amount
            if stroke['layer'] in ('skin', 'hair', 'fabric'):
                for other in ('skin', 'hair', 'fabric'):
                    if other != stroke['layer']:
                        fields[other] *= 1 - amount
                fields['confidence'] += (1 - fields['confidence']) * amount
