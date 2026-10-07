"""Apply a checksum-bound reviewed source patch in the isolated CI branch.

The payload is a unified text diff plus before/after hashes, not executable code.
CI stages the resulting ordinary readable source files only after all tests pass.
"""
from __future__ import annotations
import hashlib
import json
import lzma
from pathlib import Path
import subprocess
import sys

EXPECTED = '4f76f46ed6fd2c518757fc4b05f560a5fd1fd96dd6037e2b8d40901158630eea'

def digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def main():
    root = Path(__file__).resolve().parents[1]
    raw = b''.join((root / 'scripts' / 'seongnam_patch_payload' / f'part{i:02d}.xzpart').read_bytes() for i in range(5))
    if hashlib.sha256(raw).hexdigest() != EXPECTED:
        raise ValueError('Patch payload checksum mismatch')
    data = json.loads(lzma.decompress(raw))
    paths = list(data['files'])
    for name in paths:
        target = root / name
        if target.is_symlink() or not target.resolve().is_relative_to(root) or '.git' in Path(name).parts:
            raise ValueError('Unsafe patch path')
    matches = all(digest(root / name) == entry['after'] for name, entry in data['files'].items())
    if '--stage' in sys.argv:
        if not matches:
            raise ValueError('Reviewed final source hash differs before staging')
        subprocess.run(['git', 'add', '--', *paths], cwd=root, check=True)
        return
    if matches:
        print('Reviewed source already matches')
        return
    for name, entry in data['files'].items():
        if digest(root / name) != entry['before']:
            raise ValueError('Base source hash differs: ' + name)
    patch = data['patch'].encode('utf-8')
    subprocess.run(['git', 'apply', '--check', '-'], input=patch, cwd=root, check=True)
    subprocess.run(['git', 'apply', '-'], input=patch, cwd=root, check=True)
    for name, entry in data['files'].items():
        if digest(root / name) != entry['after']:
            raise ValueError('Applied source hash differs: ' + name)
    print(f'Applied {len(paths)} reviewed source files; all hashes match')

if __name__ == '__main__':
    main()
