"""Source-grid structural region checks."""


def validate_regions(regions, width, height):
    if not 1 <= len(regions) <= 64:
        raise ValueError("Supply between 1 and 64 structural rectangles")
    for region in regions:
        if len(region) != 4 or any(type(value) is not int for value in region):
            raise ValueError("Rectangles require integer x, y, width and height")
        x, y, w, h = region
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
            raise ValueError("Rectangle falls outside the saved base grid")
    return [list(region) for region in regions]


def measure_region(base, candidate, region, stripe_rows):
    """Count RGB changes and directional edge disagreements on the same grid."""
    import numpy as np

    x, y, width, height = region
    changed_pixels = 0
    changed_edges = 0

    def luminance(rgb):
        # Approximate 8-bit luminance with integer weights that sum to 256.
        rgb = rgb.astype(np.int32)
        return (77 * rgb[..., 0] + 150 * rgb[..., 1] + 29 * rgb[..., 2]) >> 8

    def edge_changes(a, b, axis):
        da = np.diff(a, axis=axis)
        db = np.diff(b, axis=axis)
        # Retain polarity so an inverted strong edge is also counted.
        ea = np.sign(da) * (np.abs(da) >= 24)
        eb = np.sign(db) * (np.abs(db) >= 24)
        return int(np.count_nonzero(ea != eb))

    for start in range(y, y + height, stripe_rows):
        end = min(start + stripe_rows, y + height)
        # Include the next row for vertical edges across stripe boundaries.
        stop = min(end + 1, y + height)
        a = base[start:stop, x:x + width]
        b = candidate[start:stop, x:x + width]
        rows = end - start
        changed_pixels += int(np.count_nonzero(np.any(a[:rows] != b[:rows], axis=2)))
        la, lb = luminance(a), luminance(b)
        changed_edges += edge_changes(la[:rows], lb[:rows], axis=1)
        changed_edges += edge_changes(la, lb, axis=0)

    return {
        "rectangle": region,
        "pixels": width * height,
        "changed_pixels": changed_pixels,
        "strong_edge_disagreements": changed_edges,
    }
