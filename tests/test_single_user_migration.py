from pathlib import Path

import pytest

from scripts.migrate_single_user import migration_plan


def test_migration_maps_kb_and_artifacts_without_modifying_files(tmp_path):
    source = tmp_path / "old"
    kb = source / "knowledge_bases" / "demo" / "raw" / "note.txt"
    artifact = source / "artifacts" / "edu-studio" / "run" / "run.json"
    for path in [kb, artifact]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original")
    data = tmp_path / "data"
    plan = migration_plan(source, data, data / "user")
    assert (kb, data / "knowledge_bases/demo/raw/note.txt") in plan
    assert (artifact, data / "user/edu-studio/run/run.json") in plan
    assert not data.exists()
    assert kb.read_text() == "original"


def test_migration_rejects_conflicts_before_copy(tmp_path):
    source = tmp_path / "old"
    source.mkdir()
    (source / "note.txt").write_text("old")
    target = tmp_path / "data" / "user"
    target.mkdir(parents=True)
    (target / "note.txt").write_text("keep")
    with pytest.raises(ValueError, match="Conflicting"):
        migration_plan(source, tmp_path / "data", target)
    assert (target / "note.txt").read_text() == "keep"


def test_migration_rejects_destination_symlink_escape(tmp_path):
    source = tmp_path / "old"
    source.mkdir()
    (source / "note.txt").write_text("old")
    target = tmp_path / "data" / "user"
    target.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    (target / "note.txt").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink escapes"):
        migration_plan(source, tmp_path / "data", target)
    assert outside.read_text() == "keep"


def test_worker_rag_uses_shared_kb_without_account_profile(monkeypatch):
    import asyncio

    from scripts import run_queue_worker as worker

    seen = {}
    async def fake_search(**kwargs):
        seen.update(kwargs)
        return {"answer": "ok"}
    monkeypatch.setattr(worker, "rag_search", fake_search)
    result = asyncio.run(worker.run_rag_query({"query": "hello", "kb_name": "demo"}, None))
    assert result == {"answer": "ok"}
    assert seen["kb_base_dir"] == worker.DEFAULT_KB_BASE_DIR
