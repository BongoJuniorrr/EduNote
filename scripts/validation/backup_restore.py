#!/usr/bin/env python3
"""Checksummed snapshots and safe isolated restores. Run with access to all sources.

All output is private (0700 directories, 0600 files). SQLite databases use the
online backup API, including committed WAL transactions. Quiesce application
writers for a cross-service point-in-time snapshot. Cache/model downloads are
not backups. A restore never overwrites an existing directory.
"""
from contextlib import closing
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def is_sqlite(path):
    with path.open('rb') as stream:
        return stream.read(16) == b'SQLite format 3\x00'


def safe_path(root, relative):
    rel = Path(relative)
    if rel.is_absolute() or not rel.parts or any(part in ('..', '.') for part in rel.parts):
        raise ValueError('Unsafe snapshot path')
    path = root / rel
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Snapshot path escapes root')
    if any(p.is_symlink() for p in [path, *path.parents] if p.is_relative_to(root)):
        raise ValueError('Symlinks are not allowed in snapshots')
    return path


def inventory(root):
    files = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError(f'Symlink in source: {path.name}')
        if path.is_file():
            files.append(path)
    return files


def snapshot(sources, destination):
    destination = destination.absolute()
    if destination.exists():
        raise ValueError('Snapshot destination already exists')
    for label, root in sources.items():
        if not label.isidentifier() or not root.is_dir():
            raise ValueError('Each source needs a unique identifier and an existing directory')
        if destination.resolve().is_relative_to(root.resolve()):
            raise ValueError('Backup destination must be outside source directories')
    destination.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    stage = Path(tempfile.mkdtemp(prefix='.backup-', dir=destination.parent))
    try:
        entries = []
        directories = []
        for label, root in sources.items():
            source_files = inventory(root)
            databases = {p for p in source_files if is_sqlite(p)}
            sidecars = {Path(str(p) + suffix) for p in databases for suffix in ('-wal', '-shm', '-journal')}
            stable = {}
            for directory in [root, *sorted(p for p in root.rglob('*') if p.is_dir())]:
                relative = str(Path(label) / directory.relative_to(root))
                (stage / relative).mkdir(parents=True, exist_ok=True, mode=0o700)
                directories.append(relative)
            for source in source_files:
                if source in sidecars:
                    continue
                relative = str(Path(label) / source.relative_to(root))
                target = safe_path(stage, relative)
                if source in databases:
                    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True, timeout=30)) as db:
                        with closing(sqlite3.connect(target)) as copied:
                            db.backup(copied)
                            copied.execute("PRAGMA journal_mode=DELETE")
                            if copied.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                                raise ValueError('SQLite integrity check failed')
                else:
                    before = digest(source)
                    shutil.copyfile(source, target)
                    stable[source] = before
                    if digest(target) != before:
                        raise ValueError('Source changed while copying; quiesce writers and retry')
                target.chmod(0o600)
                entries.append({'path': relative, 'bytes': target.stat().st_size, 'sha256': digest(target), 'sqlite': source in databases})
            if ([p for p in inventory(root) if p not in sidecars]
                    != [p for p in source_files if p not in sidecars]
                    or any(digest(path) != value for path, value in stable.items())):
                raise ValueError('Sources changed during snapshot; quiesce writers and retry')
        manifest = {'format': 1, 'created_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                    'directories': directories, 'files': entries,
                    'consistency': 'SQLite online backup; stable non-database files. Quiesce all writers for a cross-service recovery point.'}
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        (stage / 'manifest.json').chmod(0o600)
        stage.rename(destination)
        return {'files': len(entries), 'sqlite_databases': len([e for e in entries if e['sqlite']]),
                'bytes': sum(e['bytes'] for e in entries), 'elapsed_seconds': time.monotonic() - started,
                'manifest_sha256': digest(destination / 'manifest.json')}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def verify(snapshot_dir):
    if snapshot_dir.is_symlink():
        raise ValueError('Snapshot root cannot be a symlink')
    manifest = json.loads((snapshot_dir / 'manifest.json').read_text())
    if manifest.get('format') != 1:
        raise ValueError('Unsupported snapshot format')
    seen = set()
    for directory in manifest['directories']:
        if not safe_path(snapshot_dir, directory).is_dir():
            raise ValueError('Snapshot directory missing')
    for entry in manifest['files']:
        path = safe_path(snapshot_dir, entry['path'])
        if entry['path'] in seen or not path.is_file() or path.stat().st_size != entry['bytes'] or digest(path) != entry['sha256']:
            raise ValueError('Snapshot checksum/size mismatch or duplicate path')
        seen.add(entry['path'])
        if entry['sqlite']:
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
                if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('Snapshot database corrupt')
    actual = {str(p.relative_to(snapshot_dir)) for p in inventory(snapshot_dir)}
    if actual != seen | {'manifest.json'}:
        raise ValueError('Snapshot contains unlisted files')
    return manifest


def restore(snapshot_dir, destination):
    started = time.monotonic()
    manifest = verify(snapshot_dir)
    if destination.exists() or destination.is_symlink():
        raise ValueError('Restore requires a new, nonexistent destination')
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.restore-', dir=destination.parent))
    try:
        for directory in manifest['directories']:
            safe_path(stage, directory).mkdir(parents=True, exist_ok=True, mode=0o700)
        for entry in manifest['files']:
            target = safe_path(stage, entry['path'])
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copyfile(safe_path(snapshot_dir, entry['path']), target)
            target.chmod(0o600)
            if digest(target) != entry['sha256']:
                raise ValueError('Restored checksum differs')
        shutil.copyfile(snapshot_dir / 'manifest.json', stage / 'manifest.json')
        (stage / 'manifest.json').chmod(0o600)
        verify(stage)
        stage.rename(destination)
        return {'restored_files': len(manifest['files']), 'elapsed_seconds': time.monotonic() - started,
                'verified_sha256': True, 'sqlite_integrity': True}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['snapshot', 'verify', 'restore'])
    p.add_argument('--source', action='append', default=[], help='label=/absolute/path (repeat)')
    p.add_argument('--snapshot', type=Path, required=True)
    p.add_argument('--destination', type=Path)
    args = p.parse_args()
    if args.action == 'snapshot':
        pairs = [item.split('=', 1) for item in args.source]
        sources = {label: Path(path).resolve() for label, path in pairs}
        if not sources or len(sources) != len(pairs):
            p.error('Supply unique --source labels')
        result = snapshot(sources, args.snapshot)
    elif args.action == 'restore':
        if args.destination is None:
            p.error('--destination is required')
        result = restore(args.snapshot, args.destination)
    else:
        result = {'verified_files': len(verify(args.snapshot)['files']), 'verified_sha256': True}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
