"""Disaster recovery: WAL consistency, corruption detection and safe destinations."""
import importlib.util
from pathlib import Path
import json
import sqlite3

import pytest

spec = importlib.util.spec_from_file_location('edunote_backup', Path(__file__).parents[1] / 'scripts/validation/backup_restore.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def test_restore_includes_wal_and_private_settings(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    (source / 'settings.json').write_text('{"active_model":"local"}')
    (source / 'empty_artifacts').mkdir()
    db = sqlite3.connect(source / 'queue.sqlite3')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE jobs (id INTEGER, status TEXT)')
    db.execute("INSERT INTO jobs VALUES (1, 'completed')"); db.commit()
    result = backup.snapshot({'user': source}, tmp_path / 'snapshot')
    assert result['sqlite_databases'] == 1
    backup.restore(tmp_path / 'snapshot', tmp_path / 'restored')
    with sqlite3.connect(tmp_path / 'restored/user/queue.sqlite3') as restored:
        assert restored.execute('SELECT status FROM jobs').fetchone() == ('completed',)
        assert restored.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    assert (tmp_path / 'restored/user/settings.json').read_bytes() == (source / 'settings.json').read_bytes()
    assert (tmp_path / 'restored/user/empty_artifacts').is_dir()
    assert (tmp_path / 'restored/user/settings.json').stat().st_mode & 0o777 == 0o600
    db.close()


def fixture_snapshot(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    (source / 'file').write_text('retained')
    backup.snapshot({'user': source}, tmp_path / 'snapshot')
    return tmp_path / 'snapshot'


def test_checksum_failure_does_not_create_restore(tmp_path):
    snap = fixture_snapshot(tmp_path)
    (snap / 'user/file').write_text('tampered')
    with pytest.raises(ValueError, match='checksum'):
        backup.restore(snap, tmp_path / 'restore')
    assert not (tmp_path / 'restore').exists()


def test_restore_never_overwrites_existing_data(tmp_path):
    snap = fixture_snapshot(tmp_path)
    destination = tmp_path / 'existing'; destination.mkdir()
    marker = destination / 'important'; marker.write_text('keep')
    with pytest.raises(ValueError, match='nonexistent'):
        backup.restore(snap, destination)
    assert marker.read_text() == 'keep'


def test_rejects_manifest_traversal(tmp_path):
    snap = fixture_snapshot(tmp_path)
    manifest = json.loads((snap / 'manifest.json').read_text())
    manifest['files'][0]['path'] = '../outside'
    (snap / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Unsafe'):
        backup.verify(snap)


def test_rejects_symlinks_and_recursive_backup(tmp_path):
    source = tmp_path / 'source'; source.mkdir()
    (source / 'link').symlink_to('/etc/passwd')
    with pytest.raises(ValueError, match='Symlink'):
        backup.snapshot({'user': source}, tmp_path / 'snapshot')
    (source / 'link').unlink()
    with pytest.raises(ValueError, match='outside'):
        backup.snapshot({'user': source}, source / 'snapshot')


def test_unlisted_file_is_rejected(tmp_path):
    snap = fixture_snapshot(tmp_path)
    (snap / 'extra').write_text('not in manifest')
    with pytest.raises(ValueError, match='unlisted'):
        backup.verify(snap)
