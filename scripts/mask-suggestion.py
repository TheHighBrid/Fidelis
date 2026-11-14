#!/usr/bin/env python3
"""Inspect, stage or resolve source-bound mask suggestions."""
import argparse
import json
from pathlib import Path
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fidelis.studio.store import JobStore
from fidelis.studio.suggestions import decode_scores,MAX_SCORE_BYTES


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('describe','stage','propose','accept','discard'))
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--job',required=True)
    parser.add_argument('--expected-revision',type=int)
    parser.add_argument('--probabilities',type=Path)
    parser.add_argument('--receipt',type=Path)
    parser.add_argument('--weights', type=Path, help='Pinned local SegFormer B0 ONNX export for propose')
    args=parser.parse_args()
    try:
        store=JobStore(args.workspace)
        if args.operation=='describe':
            job=store.get(args.job)
        else:
            if args.expected_revision is None:raise ValueError('Use an explicit saved revision')
            if args.operation=='stage':
                if not args.probabilities or not args.receipt:raise ValueError('Select probabilities NPZ and JSON receipt')
                if args.probabilities.stat().st_size>MAX_SCORE_BYTES or args.receipt.stat().st_size>1024**2:
                    raise ValueError('Probability/receipt file exceeds limit')
                scores=decode_scores(args.probabilities.read_bytes())
                receipt=json.loads(args.receipt.read_text())
                job=store.stage_suggestion(args.job,scores,receipt,expected_revision=args.expected_revision)
            elif args.operation == 'propose':
                if args.weights is None:
                    raise ValueError('Supply --weights for local SegFormer inference')
                from fidelis.studio.segformer import propose

                job = propose(store, args.job, args.expected_revision, args.weights)
            else:
                job=store.resolve_suggestion(args.job,expected_revision=args.expected_revision,accept=args.operation=='accept')
        print(json.dumps({key:job[key] for key in ('id','revision','dimensions')} | {
              'base_artifact_sha256':job['artifacts']['base']['sha256'],
              'mask_suggestion':job.get('mask_suggestion')},allow_nan=False,indent=2))
    except (ValueError,OSError,KeyError,TypeError,zipfile.BadZipFile) as error:
        parser.exit(2,f'mask-suggestion: {error}\n')


if __name__=='__main__':main()
