"""Publish local browser acceptance artifacts without following destination links.

The operator supplies the destination, never the browser. Resolve the parent
once (including platform aliases such as macOS /tmp), then pin each directory
using no-follow descriptors. All staging, validation and publication occur
relative to the final pinned directory, not a mutable absolute path.
"""

import os
from pathlib import Path
import stat
import sys
import uuid


def _open_directory(path):
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:]:
            try:
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _require_regular_destination(directory, name):
    try:
        existing = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(existing.st_mode):
        raise ValueError("Acceptance report destination must be a regular file")


def publish_evidence(destination, payload):
    """Atomically publish bytes in the operator's chosen directory, mode 0600."""
    target = Path(destination)
    if not target.name or target.name in ('.', '..'):
        raise ValueError("Acceptance report destination must be a regular file")
    directory = _open_directory(target.parent.resolve())
    staging = f'.fidelis-report-{uuid.uuid4().hex}'
    try:
        _require_regular_destination(directory, target.name)
        os.mkdir(staging, mode=0o700, dir_fd=directory)
        try:
            _publish_from_staging(directory, staging, target.name, payload)
        finally:
            os.rmdir(staging, dir_fd=directory)
    finally:
        os.close(directory)


def _publish_from_staging(directory, staging, name, payload):
    stage_fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        fd = os.open('receipt', flags, 0o600, dir_fd=stage_fd)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            _require_regular_destination(directory, name)
            os.replace('receipt', name, src_dir_fd=stage_fd, dst_dir_fd=directory)
        finally:
            try:
                os.unlink('receipt', dir_fd=stage_fd)
            except FileNotFoundError:
                pass
    finally:
        os.close(stage_fd)


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Expected exactly one evidence destination')
    try:
        publish_evidence(sys.argv[1], sys.stdin.buffer.read())
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == '__main__':
    main()
