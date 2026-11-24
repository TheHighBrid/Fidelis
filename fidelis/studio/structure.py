"""Source-grid structural region checks and bounded-stripe heuristic proposals."""

from collections import deque


def _require_int(value, name, *, minimum=1, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return value


def _luminance(rgb):
    import numpy as np

    # Approximate 8-bit luminance with integer weights that sum to 256.
    arr = rgb.astype(np.int32)
    return (77 * arr[..., 0] + 150 * arr[..., 1] + 29 * arr[..., 2]) >> 8


def _validate_rgb8(array, name="base"):
    import numpy as np

    if (not isinstance(array, np.ndarray) or array.ndim != 3
            or array.shape[2] != 3 or array.dtype != np.uint8):
        raise ValueError(f"{name} must be an aligned RGB8 array")
    if array.shape[0] <= 0 or array.shape[1] <= 0:
        raise ValueError(f"{name} dimensions must be positive")
    return array


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

    _require_int(stripe_rows, "stripe_rows", minimum=1)
    if (not isinstance(base, np.ndarray) or not isinstance(candidate, np.ndarray)
            or base.shape != candidate.shape or base.ndim != 3
            or base.shape[2] != 3 or base.dtype != np.uint8
            or candidate.dtype != np.uint8):
        raise ValueError("Structural comparison requires aligned RGB8 arrays")
    if len(region) != 4 or any(type(value) is not int for value in region):
        raise ValueError("Structural rectangle requires integer x, y, width and height")
    x, y, width, height = region
    if (x < 0 or y < 0 or width <= 0 or height <= 0
            or x + width > base.shape[1] or y + height > base.shape[0]):
        raise ValueError("Structural rectangle must fit the source grid")
    changed_pixels = 0
    changed_edges = 0

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
        la, lb = _luminance(a), _luminance(b)
        changed_edges += edge_changes(la[:rows], lb[:rows], axis=1)
        changed_edges += edge_changes(la, lb, axis=0)

    return {
        "rectangle": region,
        "pixels": width * height,
        "changed_pixels": changed_pixels,
        "strong_edge_disagreements": changed_edges,
    }


def _connected_cell_components(active, cell_edges):
    grid_h, grid_w = active.shape
    visited = [[False] * grid_w for _ in range(grid_h)]
    components = []
    for sy in range(grid_h):
        for sx in range(grid_w):
            if not active[sy, sx] or visited[sy][sx]:
                continue
            queue = deque([(sy, sx)])
            visited[sy][sx] = True
            min_cy = max_cy = sy
            min_cx = max_cx = sx
            edge_sum = 0
            while queue:
                cy, cx = queue.popleft()
                edge_sum += int(cell_edges[cy, cx])
                min_cy = min(min_cy, cy)
                max_cy = max(max_cy, cy)
                min_cx = min(min_cx, cx)
                max_cx = max(max_cx, cx)
                for ny in range(max(0, cy - 1), min(grid_h, cy + 2)):
                    for nx in range(max(0, cx - 1), min(grid_w, cx + 2)):
                        if active[ny, nx] and not visited[ny][nx]:
                            visited[ny][nx] = True
                            queue.append((ny, nx))
            components.append((min_cx, min_cy, max_cx, max_cy, edge_sum))
    return components


def _accumulate_cell_edges(base, *, stripe_rows, cell_size, edge_threshold):
    import numpy as np

    height, width = base.shape[:2]
    grid_h = (height + cell_size - 1) // cell_size
    grid_w = (width + cell_size - 1) // cell_size
    padded_w = grid_w * cell_size
    cell_edges = np.zeros((grid_h, grid_w), dtype=np.int32)

    for start in range(0, height, stripe_rows):
        end = min(start + stripe_rows, height)
        stop = min(end + 1, height)
        rows = end - start
        lum = _luminance(base[start:stop])
        row_counts = np.zeros((rows, padded_w), dtype=np.int32)
        if width > 1:
            h_edges = np.abs(np.diff(lum[:rows], axis=1)) >= edge_threshold
            row_counts[:, :width - 1] += h_edges
        v_rows = stop - start - 1
        if v_rows > 0:
            v_edges = np.abs(np.diff(lum, axis=0)) >= edge_threshold
            row_counts[:v_rows, :width] += v_edges
        col_sums = row_counts.reshape((rows, grid_w, cell_size)).sum(axis=2)
        first_cy = start // cell_size
        last_cy = (end - 1) // cell_size
        for cy in range(first_cy, last_cy + 1):
            r0 = max(start, cy * cell_size) - start
            r1 = min(end, (cy + 1) * cell_size) - start
            cell_edges[cy] += col_sums[r0:r1].sum(axis=0)
    return cell_edges


def _build_proposals(cell_edges, width, height, config):
    import numpy as np

    min_edges = config["min_edges_per_cell"]
    threshold_used = (
        int(min_edges)
        if min_edges is not None
        else max(16, int(np.percentile(cell_edges, 80)))
    )
    active = cell_edges >= threshold_used
    cell_size = config["cell_size"]
    padding = config["padding"]
    min_area = config["min_area"]
    proposals = []
    for min_cx, min_cy, max_cx, max_cy, edge_sum in _connected_cell_components(active, cell_edges):
        x0 = max(0, min_cx * cell_size - padding)
        y0 = max(0, min_cy * cell_size - padding)
        x1 = min(width, (max_cx + 1) * cell_size + padding)
        y1 = min(height, (max_cy + 1) * cell_size + padding)
        w, h = x1 - x0, y1 - y0
        pixels = w * h
        if pixels < min_area:
            continue
        proposals.append({
            "rectangle": [int(x0), int(y0), int(w), int(h)],
            "pixels": int(pixels),
            "strong_edges": int(edge_sum),
            "edge_density": round(edge_sum / float(pixels), 4),
        })
    proposals.sort(
        key=lambda item: (-item["edge_density"], -item["strong_edges"], item["rectangle"][1], item["rectangle"][0])
    )
    return proposals[:config["max_proposals"]]


def propose_regions(
    base,
    *,
    stripe_rows=256,
    cell_size=16,
    edge_threshold=24,
    min_edges_per_cell=None,
    min_area=64,
    max_proposals=16,
    padding=4,
):
    """Propose candidate structural rectangles via bounded-stripe luminance-edge clustering.

    This is a contrast heuristic for flagging dense edges (potential typography,
    logos, seams, zippers, or hardware) for operator review. It is not semantic
    recognition and never locks pixels without explicit confirmation.
    """
    _validate_rgb8(base, "base")
    _require_int(stripe_rows, "stripe_rows", minimum=1)
    _require_int(cell_size, "cell_size", minimum=4)
    _require_int(edge_threshold, "edge_threshold", minimum=1)
    if min_edges_per_cell is not None:
        _require_int(min_edges_per_cell, "min_edges_per_cell", minimum=1)
    _require_int(min_area, "min_area", minimum=1)
    _require_int(max_proposals, "max_proposals", minimum=1, maximum=64)
    _require_int(padding, "padding", minimum=0)

    height, width = base.shape[:2]
    cell_edges = _accumulate_cell_edges(
        base,
        stripe_rows=stripe_rows,
        cell_size=cell_size,
        edge_threshold=edge_threshold,
    )
    proposals = _build_proposals(
        cell_edges,
        width,
        height,
        {
            "cell_size": cell_size,
            "min_edges_per_cell": min_edges_per_cell,
            "min_area": min_area,
            "max_proposals": max_proposals,
            "padding": padding,
        },
    )
    return {
        "schema_version": 1,
        "dimensions": [int(width), int(height)],
        "semantic_proof": False,
        "heuristic_notice": (
            "Dense luminance-edge clusters are contrast proposals only; they do not "
            "verify OCR/logo/hardware semantics and never auto-lock pixels without review."
        ),
        "proposals": proposals,
    }
