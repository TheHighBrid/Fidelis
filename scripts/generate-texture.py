#!/usr/bin/env python3
"""Generate an aligned texture through an explicitly configured local ComfyUI graph."""
import argparse
import json
from pathlib import Path
import sys
import uuid

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fidelis.studio.comfy import ComfyTextureBackend
from fidelis.studio.png import read_rgb8_png
from fidelis.studio.store import JobStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workflow', type=Path, help='Versioned workflow bundle containing exported API graph')
    parser.add_argument('output', type=Path, help='Texture PNG output, separate from source')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--source', type=Path, help='Pre-scaled, untagged sRGB RGB PNG')
    group.add_argument('--job', help='Existing regional job ID to update')
    parser.add_argument('--workspace', type=Path, default=Path('.cache/web_outputs/region_jobs'))
    parser.add_argument('--runs', type=Path, default=Path('.cache/generation_runs'))
    parser.add_argument('--address', default='http://127.0.0.1:8188')
    parser.add_argument('--run-id', help='Explicit UUID to resume; default is derived from source + recipe')
    parser.add_argument('--deadline', type=float, default=300)
    args = parser.parse_args()
    backend = None
    try:
        bundle = json.loads(args.workflow.read_text(encoding='utf-8'))
        if args.output.suffix.lower() != '.png':
            raise ValueError('Output must be PNG')
        targets = {args.output.resolve(), args.output.with_suffix('.png.recipe.json').resolve()}
        if args.workflow.resolve() in targets or (args.source and args.source.resolve() in targets):
            raise ValueError('Output must not overwrite an input')
        if args.job:
            store = JobStore(args.workspace)
            job = store.get(args.job)
            if job['profile'] == 'packshot_strict':
                raise ValueError('Packshot Strict never invokes a generative backend')
            with store.open_array(args.job, 'base', expected_revision=job['revision']) as base:
                source = np.array(base)
        else:
            with args.source.open('rb') as stream:
                source = read_rgb8_png(stream)
        backend = ComfyTextureBackend(args.runs, args.address)
        run_id = args.run_id or backend.default_cli_run_id(source, bundle, args.address)
        print(f'Generation run ID: {run_id}', file=sys.stderr)
        texture, record = backend.run(source, bundle, run_id=run_id, deadline_seconds=args.deadline)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        pending = args.output.with_suffix(f'.{uuid.uuid4().hex}.pending')
        Image.fromarray(texture).save(pending, format='PNG')
        pending.replace(args.output)
        args.output.with_suffix('.png.recipe.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
        if args.job:
            updated = store.replace_texture(args.job, texture, expected_revision=job['revision'], candidate_recipe=record)
            print(json.dumps({'texture': str(args.output), 'job_id': args.job, 'revision': updated['revision']}))
        else:
            print(json.dumps({'texture': str(args.output), 'run_id': run_id, 'status': record['status']}))
    except Exception as error:
        parser.exit(2, f'generate-texture: {error}\n')
    finally:
        if backend:
            backend.close()


if __name__ == '__main__':
    main()
