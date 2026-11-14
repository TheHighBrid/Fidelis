#!/usr/bin/env python3
"""Audit explicit corpus inventory or create/verify an unsigned frozen snapshot."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fidelis.eval.corpus_manifest import audit,freeze,verify


def load(path):
    if path.stat().st_size>8*1024**2:raise ValueError('Manifest exceeds 8 MiB')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate JSON key')
            result[key]=value
        return result
    return json.loads(path.read_text(),object_pairs_hook=unique,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def write_new(path,record):
    # Never overwrite source images, permissions, a prior lock or any other file.
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(record,stream,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('audit','freeze','verify'))
    parser.add_argument('input',type=Path)
    parser.add_argument('--root',type=Path,default=Path.cwd(),help='Explicit local root for assets/evidence')
    parser.add_argument('--protocol',type=Path,default=Path('config/benchmark/protocol-v1.json'))
    parser.add_argument('--slots',type=Path,default=Path('config/benchmark/slots-v1.json'))
    parser.add_argument('--output',type=Path,help='New lock file for freeze; never overwritten')
    parser.add_argument('--require-ready',action='store_true',help='Audit exits 1 until the production corpus is complete')
    args=parser.parse_args()
    try:
        item=load(args.input)
        if args.operation=='verify':report=verify(item,args.root)
        else:
            protocol,slots=load(args.protocol),load(args.slots)
            report=audit(item,protocol,slots,args.root)
            if args.operation=='freeze':
                if args.output is None:raise ValueError('freeze requires --output')
                record=freeze(item,protocol,slots,args.root);write_new(args.output,record)
                report={'lock_sha256':record['lock_sha256'],'production_ready':True,'output':str(args.output)}
        print(json.dumps(report,indent=2,allow_nan=False))
        return 1 if args.require_ready and not report['production_ready'] else 0
    except (ValueError,OSError,KeyError,TypeError) as error:
        parser.exit(2,f'benchmark-corpus: {error}\n')


if __name__=='__main__':sys.exit(main())
