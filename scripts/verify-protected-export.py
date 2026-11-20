"""Offline, fail-closed verification of exact protected RGB export pixels.

This is an independent acceptance aid, not a geometric registration or model-quality test.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def verify(base_path, export_path, mask_path):
    with Image.open(base_path) as base_image, Image.open(export_path) as output_image:
        if base_image.format != 'PNG' or output_image.format != 'PNG':
            raise ValueError('base and export must be PNG files')
        if base_image.mode != 'RGB' or output_image.mode != 'RGB':
            raise ValueError('base and export must be untagged 8-bit RGB')
        if base_image.info.get('icc_profile') or output_image.info.get('icc_profile'):
            raise ValueError('ICC-tagged inputs are outside this verifier contract')
        if any(any(key in image.info for key in ('gamma', 'srgb', 'chromaticity'))
               for image in (base_image, output_image)):
            raise ValueError('PNG colour-transfer metadata is outside this verifier contract')
        if any('transparency' in image.info for image in (base_image, output_image)):
            raise ValueError('PNG transparency is outside this verifier contract')
        if any(image.getexif().get(274, 1) != 1 for image in (base_image, output_image)):
            raise ValueError('EXIF orientation changes are outside this verifier contract')
        if base_image.size != output_image.size:
            raise ValueError('export dimensions differ from base')
        base = np.asarray(base_image)
        output = np.asarray(output_image)
    with np.load(mask_path, allow_pickle=False) as data:
        if 'protect' not in data.files:
            raise ValueError('NPZ requires a protect mask')
        mask = data['protect']
    if mask.shape != base.shape[:2] or mask.dtype.kind not in 'fiu':
        raise ValueError('protect mask must be a numeric HxW array')
    if not np.all(np.isfinite(mask)) or np.any((mask < 0) | (mask > 1)):
        raise ValueError('protect mask values must be finite within [0,1]')
    locked = mask == 1
    if not np.any(locked):
        raise ValueError('protect mask has no fully locked pixels; no protected-pixel assertion is possible')
    changed = np.any(base != output, axis=2) & locked
    count = int(np.count_nonzero(changed))
    return {'pass': count == 0, 'protected_pixels': int(np.count_nonzero(locked)),
            'changed_protected_pixels': count, 'width': int(base.shape[1]), 'height': int(base.shape[0])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path)
    parser.add_argument('export', type=Path)
    parser.add_argument('masks', type=Path, help='NPZ containing protect mask, with 1.0 fully locked')
    args = parser.parse_args(argv)
    try:
        result = verify(args.base, args.export, args.masks)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # This field is the boolean verification verdict, not a credential.
        verification_passed = False
        print(json.dumps({'pass': verification_passed, 'error': str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
