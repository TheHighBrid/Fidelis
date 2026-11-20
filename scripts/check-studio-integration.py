#!/usr/bin/env python3
"""Fail-closed history preflight for a Studio integration branch.

Does not certify tests, conflict resolution, image quality or release readiness.
"""
import argparse
import subprocess
import sys


def git(*args, cwd=None):
    result = subprocess.run(['git', *args], cwd=cwd, text=True,
                            capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def inspect(base, head, cwd=None):
    if not base or not head or base == head:
        raise ValueError('Distinct nonempty base and head refs are required')
    root = git('rev-parse', '--show-toplevel', cwd=cwd)
    if git('status', '--porcelain', cwd=root):
        raise RuntimeError('Working tree is not clean; refusing integration preflight')
    # Pin refs before inspection so a concurrent branch update cannot mix
    # different histories across merge, ahead/behind and diff checks.
    base_sha = git('rev-parse', '--verify', f'{base}^{{commit}}', cwd=root)
    head_sha = git('rev-parse', '--verify', f'{head}^{{commit}}', cwd=root)
    merge_base = git('merge-base', base_sha, head_sha, cwd=root)
    # Git's merge-tree performs an in-memory three-way merge, without touching
    # the index or working tree. Nonzero exit means conflict or unsupported Git.
    merge_check = subprocess.run(['git', 'merge-tree', '--write-tree', base_sha, head_sha],
                                 cwd=root, text=True, capture_output=True,
                                 check=False)
    if merge_check.returncode:
        raise RuntimeError('Integration merge-tree failed or has conflicts: ' +
                           (merge_check.stderr.strip() or merge_check.stdout.strip())[:500])
    ahead = int(git('rev-list', '--count', f'{base_sha}..{head_sha}', cwd=root))
    behind = int(git('rev-list', '--count', f'{head_sha}..{base_sha}', cwd=root))
    files = git('diff', '--name-only', f'{base_sha}...{head_sha}', cwd=root).splitlines()
    if (git('rev-parse', '--verify', f'{base}^{{commit}}', cwd=root) != base_sha
            or git('rev-parse', '--verify', f'{head}^{{commit}}', cwd=root) != head_sha):
        raise RuntimeError('Branch ref changed during integration preflight')
    # A concurrent editor may dirty the checkout after the initial status check.
    # Refuse to certify a snapshot that no longer matches the working tree.
    if git('status', '--porcelain', cwd=root):
        raise RuntimeError('Working tree changed during integration preflight')
    return {'base': base, 'head': head, 'base_sha': base_sha,
            'head_sha': head_sha, 'merge_base': merge_base,
            'ahead': ahead, 'behind': behind, 'files': files}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--head', required=True)
    parser.add_argument('--repo', default='.')
    args = parser.parse_args(argv)
    try:
        result = inspect(args.base, args.head, args.repo)
    except (ValueError, RuntimeError) as exc:
        print(f'BLOCKED: {exc}', file=sys.stderr)
        return 2
    print(f"base={result['base']} head={result['head']} merge_base={result['merge_base']}")
    print(f"ahead={result['ahead']} behind={result['behind']}")
    print('changed_files=' + ','.join(result['files']))
    if result['behind']:
        print('BLOCKED: branch is missing base commits; reconcile and retest', file=sys.stderr)
        return 1
    if not result['ahead']:
        print('BLOCKED: no feature commits to integrate', file=sys.stderr)
        return 1
    print('History preflight passed; tests, diff review and signoff remain separate.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
