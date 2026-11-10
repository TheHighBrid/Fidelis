#!/usr/bin/env python3
"""Report actual installed model files and local ComfyUI reachability as JSON."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fidelis.studio.capabilities import inventory
from fidelis.studio.comfy import ComfyTextureBackend

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-home', type=Path)
    parser.add_argument('--address', default='http://127.0.0.1:8188')
    parser.add_argument('--runs', type=Path, default=Path('.cache/generation_runs'))
    args = parser.parse_args()
    result = inventory(Path(__file__).resolve().parents[1], args.app_home)
    backend = ComfyTextureBackend(args.runs, args.address, timeout=1)
    try:
        result['comfyui'] = backend.probe()
    finally:
        backend.close()
    print(json.dumps(result, indent=2))
