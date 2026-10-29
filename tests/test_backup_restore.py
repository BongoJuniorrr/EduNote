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


def test_portable_backup_from_another_directory_includes_compose(tmp_path):
    import shutil
    import subprocess

    project = tmp_path / "portable"
    scripts = project / "scripts"
    (scripts / "validation").mkdir(parents=True)
    original = Path(__file__).parents[1]
    for name in ("backup_edunote.sh", "validation/backup_restore.py"):
        shutil.copy2(original / "scripts" / name, scripts / name)
    for directory in ("data/user", "data/knowledge_bases", "data/storage", "config"):
        (project / directory).mkdir(parents=True)
    for name in ("compose.yaml", "compose.gpu.yaml", "start.sh", "README.md", ".env"):
        (project / name).write_text("portable fixture")
    (project / "data/storage/retained.txt").write_text("retained content")
    subprocess.run(["bash", str(scripts / "backup_edunote.sh")], cwd=tmp_path, check=True,
                   capture_output=True)
    stamp = (project / "backups/snapshots/LATEST").read_text().strip()
    destination = tmp_path / "restored"
    backup.restore(project / "backups/snapshots" / stamp, destination)
    assert (destination / "deployment/compose.yaml").read_text() == "portable fixture"
    assert (destination / "deployment/compose.gpu.yaml").is_file()
    assert (destination / "deployment/start.sh").is_file()
    assert (destination / "storage/retained.txt").read_text() == "retained content"


def test_wal_reader_coordination_files_do_not_invalidate_snapshot(tmp_path):
    source = tmp_path / "wal_source"
    source.mkdir()
    database = source / "learning.sqlite3"
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE evidence (value TEXT)")
        db.execute("INSERT INTO evidence VALUES ('retained')")
    db.close()
    snapshot = tmp_path / "wal_snapshot"
    backup.snapshot({"learning": source}, snapshot)
    backup.restore(snapshot, tmp_path / "restored_wal")
    with sqlite3.connect(tmp_path / "restored_wal/learning/learning.sqlite3") as restored:
        assert restored.execute("SELECT value FROM evidence").fetchone() == ("retained",)
