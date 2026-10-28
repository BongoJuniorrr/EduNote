"""Contracts for sourced learning, durable cancellation and review persistence."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.services.learning.models import StudyPack
from src.services.learning.store import LearningStore
from src.services.queue.job_store import PersistentJobStore
from src.services.queue.worker import QueueWorker


def sample_pack(source="src_example"):
    claim = {"text": "A telescope collects light.", "source_ids": [source]}
    return {
        "title": "Optics",
        "goals": [claim],
        "summary": [claim],
        "concepts": [claim],
        "rubric": [claim],
        "quiz": [
            {
                **claim,
                "topic": "Optics",
                "options": ["Collect light", "Create gravity"],
                "answer": 0,
                "explanation": "The source describes collecting light.",
            }
        ],
    }


def seed(store):
    store.put("src_example", "source", {"id": "src_example", "text": "A telescope collects light."})
    store.put(
        "pack",
        "study_pack",
        {
            "title": "Optics",
            "sources": [{"id": "src_example", "text": "A telescope collects light."}],
            "pack": sample_pack(),
        },
    )
    return store.enroll("pack")["cards"][0]["id"]


def test_pack_rejects_invalid_answers_and_unknown_sources():
    pack = sample_pack()
    assert StudyPack.model_validate(pack).validate_sources({"src_example"})
    with pytest.raises(ValueError, match="unknown source"):
        StudyPack.model_validate(pack).validate_sources({"other"})
    pack["quiz"][0]["answer"] = 5
    with pytest.raises(ValueError):
        StudyPack.model_validate(pack)
    pack["quiz"][0]["answer"] = 0
    pack["quiz"][0]["options"] = ["placeholder", "Real"]
    with pytest.raises(ValueError):
        StudyPack.model_validate(pack)


def test_review_is_persistent_idempotent_and_hides_answer(tmp_path):
    path = tmp_path / "learning.db"
    store = LearningStore(path)
    card = seed(store)
    seed(store)  # enrolling twice must not reset or duplicate cards
    initial = store.review()
    assert len(initial["cards"]) == 1
    assert "answer" not in initial["cards"][0]["item"]
    assert "explanation" not in initial["cards"][0]["item"]
    response = store.answer(card, 1, 3, "attempt-one")
    assert response["correct"] is False
    assert response["interval_days"] == pytest.approx(10 / 1440)
    same = store.answer(card, 1, 3, "attempt-one")
    assert same["next_due"] == response["next_due"]
    reopened = LearningStore(path).review()
    assert reopened["attempts"] == 1 and len(reopened["cards"]) == 1
    assert reopened["topics"][0] == {"topic": "Optics", "attempts": 1, "correct": 0}
    with pytest.raises(ValueError):
        store.answer(card, 0, 2, "attempt-two")  # not due
    with pytest.raises(ValueError):
        store.answer(card, 0, 3, "attempt-one")  # reused ID


def test_spaced_review_intervals_follow_observed_success(tmp_path, monkeypatch):
    from src.services.learning import store as module

    clock = [1000.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: clock[0]))
    store = LearningStore(tmp_path / "learning.db")
    card = seed(store)
    first = store.answer(card, 0, 2, "first-attempt")
    assert first["interval_days"] == 1
    clock[0] = first["next_due"] + 1
    second = store.answer(card, 0, 2, "second-attempt")
    assert second["interval_days"] == 6
    clock[0] = second["next_due"] + 1
    third = store.answer(card, 0, 2, "third-attempt")
    assert third["interval_days"] == 15


def test_restore_merge_is_atomic_and_preserves_review_state(tmp_path):
    original = LearningStore(tmp_path / "first.db")
    card = seed(original)
    original.answer(card, 0, 2, "attempt-one")
    backup = original.export()
    restored = LearningStore(tmp_path / "restored.db")
    restored.import_backup(backup)
    assert restored.export() == backup
    restored.import_backup(backup)
    assert restored.review()["attempts"] == 1
    corrupt = json.loads(json.dumps(backup))
    corrupt["artifacts"].insert(
        0,
        {
            "id": "new",
            "kind": "evidence",
            "body": json.dumps(
                {"title": "New evidence", "sources": [], "claims": [], "status": "no_evidence"}
            ),
            "created": 1.0,
        },
    )
    corrupt["cards"][0]["due"] += 100
    with pytest.raises(ValueError, match="conflicts"):
        restored.import_backup(corrupt)
    assert restored.export() == backup  # no partially inserted artifact


def test_enqueue_deduplicates_and_scopes_request_ids(tmp_path):
    store = PersistentJobStore(tmp_path / "queue.db")
    first = store.enqueue("local", "evidence", {"topic": "one"}, request_key="request-1")
    assert (
        store.enqueue("local", "evidence", {"topic": "one"}, request_key="request-1").id == first.id
    )
    with pytest.raises(ValueError):
        store.enqueue("local", "evidence", {"topic": "other"}, request_key="request-1")
    assert len(store.list("local")) == 1
    assert store.list("someone-else") == []
    store.cancel(first.id, "local")
    assert store.claim_next() is None


def test_cancel_stops_real_child_process_before_side_effect(tmp_path, monkeypatch):
    from src.services.queue import worker as module

    store = PersistentJobStore(tmp_path / "queue.db")
    job = store.enqueue("local", "test", {})
    worker = QueueWorker(store)
    worker.register("test", lambda *_: None, isolated=True)
    ready, effect = tmp_path / "ready", tmp_path / "effect"
    real_popen = subprocess.Popen
    script = (
        "from pathlib import Path; import time; Path(%r).touch(); time.sleep(2); Path(%r).touch()"
        % (str(ready), str(effect))
    )

    def popen(*args, **kwargs):
        return real_popen([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    task = threading.Thread(target=worker.run_once)
    task.start()
    deadline = time.monotonic() + 10
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists()
    store.cancel(job.id, "local")
    task.join(timeout=5)
    assert not task.is_alive()
    time.sleep(2)
    assert not effect.exists()
    assert store.get(job.id).status == "cancelled"


def test_cancelled_job_cannot_commit_learning_artifact(tmp_path, monkeypatch):
    from src.services.queue import job_store as queue_module

    queue = PersistentJobStore(tmp_path / "queue.db")
    job = queue.enqueue("local", "evidence", {})
    queue.claim_next("worker", 60)
    monkeypatch.setattr(queue_module, "_job_store", queue)
    monkeypatch.setenv("EDUNOTE_WORKER_ID", "worker")
    monkeypatch.setenv("EDUNOTE_ACTIVE_JOB", job.id)
    store = LearningStore(tmp_path / "learning.db")
    store.put("before", "evidence", {})
    queue.cancel(job.id, "local")
    with pytest.raises(RuntimeError):
        store.put("after", "evidence", {})
    with pytest.raises(LookupError):
        store.get("after")


def test_jobs_api_rejects_untyped_payload_and_cleans_cancelled_preview(tmp_path, monkeypatch):
    from src.api.routers import jobs as routes
    from src.services import document_previews

    queue = PersistentJobStore(tmp_path / "queue.db")
    monkeypatch.setattr(routes, "get_job_store", lambda: queue)
    staged = tmp_path / "preview"
    staged.mkdir()
    (staged / "config.json").write_text("private")
    monkeypatch.setattr(document_previews, "preview_directory", lambda *_: staged)
    app = FastAPI()
    app.include_router(routes.router, prefix="/jobs")
    client = TestClient(app)
    assert client.post("/jobs", json={"kind": "unknown", "payload": {}}).status_code == 422
    job = queue.enqueue("local", "document_preview", {"preview_id": "a" * 32})
    assert client.get("/jobs").json()["jobs"][0]["id"] == job.id
    assert client.post(f"/jobs/{job.id}/cancel").json()["job"]["status"] == "cancelled"
    assert not staged.exists()


@pytest.mark.asyncio
async def test_generation_repairs_invalid_json_but_never_invents_sources(monkeypatch):
    from src.services import llm
    from src.services.learning import workflows

    calls = []

    async def invalid(*args, **kwargs):
        calls.append(kwargs)
        return json.dumps(sample_pack("invented"))

    monkeypatch.setattr(llm, "complete", invalid)
    with pytest.raises(ValueError, match="twice"):
        await workflows.generate_json(
            "test",
            StudyPack.model_json_schema(),
            lambda data: StudyPack.model_validate(data).validate_sources({"real"}),
        )
    assert len(calls) == 2
    assert all(call["max_retries"] == 0 and call["timeout"] == 300 for call in calls)


def test_diagnostic_errors_never_echo_secrets():
    from src.services.learning.workflows import safe_error

    assert "secret" not in safe_error(ValueError("https://secret.example/api?api_key=secret"))
    assert "sk-" not in safe_error(RuntimeError("Bearer sk-secret"))


def test_source_identity_is_stable_without_fake_page_or_filename():
    from src.services.learning.workflows import source_record

    first = source_record("kb", {"content": "Example"}, "index", "config")
    again = source_record("kb", {"content": "Example"}, "index", "other-config")
    assert first["id"] == again["id"]
    assert first["page_start"] is None and first["doc_name"] is None
    assert "confidence" not in first


def test_preview_source_link_detects_replaced_original(tmp_path, monkeypatch):
    import hashlib

    from src.api.routers import learning as routes
    from src.services.rag import service

    store = LearningStore(tmp_path / "learning.db")
    root = tmp_path / "kbs"
    raw = root / "demo" / "raw"
    raw.mkdir(parents=True)
    original = raw / "example.pdf"
    original.write_bytes(b"original")
    store.put(
        "source",
        "source",
        {
            "id": "source",
            "kb_name": "demo",
            "doc_name": "example.pdf",
            "document_sha256": hashlib.sha256(b"original").hexdigest(),
        },
    )
    monkeypatch.setattr(routes, "LearningStore", lambda: store)
    monkeypatch.setattr(service, "DEFAULT_KB_BASE_DIR", str(root))
    app = FastAPI()
    app.include_router(routes.router, prefix="/learning")
    client = TestClient(app)
    assert client.get("/learning/sources/source/document").content == b"original"
    original.write_bytes(b"changed")
    assert client.get("/learning/sources/source/document").status_code == 409
    store.put("bad", "source", {"id": "bad", "kb_name": "../escape", "doc_name": "outside.pdf"})
    assert client.get("/learning/sources/bad/document").status_code == 404


@pytest.mark.asyncio
async def test_evidence_with_no_sources_abstains_without_llm(tmp_path, monkeypatch):
    from src.services.learning import workflows

    store = LearningStore(tmp_path / "learning.db")
    monkeypatch.setattr(workflows, "LearningStore", lambda: store)
    monkeypatch.setattr(workflows, "verify_configuration", lambda *_: None)
    monkeypatch.setattr(workflows, "checkpoint", lambda *_: None)

    async def empty(_):
        return []

    async def forbidden(*_):
        raise AssertionError("LLM must not run without evidence")

    monkeypatch.setattr(workflows, "collect_sources", empty)
    monkeypatch.setattr(workflows, "generate_json", forbidden)
    result = await workflows.run_evidence(
        {"topic": "Unknown fact"}, SimpleNamespace(id="job-empty")
    )
    assert result["status"] == "no_evidence"
    assert store.get("job-empty")["claims"] == []


@pytest.mark.asyncio
async def test_settings_changed_mid_run_prevents_publish(tmp_path, monkeypatch):
    from src.services.learning import workflows

    store = LearningStore(tmp_path / "learning.db")
    monkeypatch.setattr(workflows, "LearningStore", lambda: store)
    monkeypatch.setattr(workflows, "checkpoint", lambda *_: None)
    calls = []

    def verify(_):
        calls.append(True)
        if len(calls) > 1:
            raise ValueError("Settings changed")

    async def empty(_):
        return []

    monkeypatch.setattr(workflows, "verify_configuration", verify)
    monkeypatch.setattr(workflows, "collect_sources", empty)
    with pytest.raises(ValueError, match="Settings changed"):
        await workflows.run_evidence({"topic": "Unknown fact"}, SimpleNamespace(id="job-changed"))
    with pytest.raises(LookupError):
        store.get("job-changed")


def test_concurrent_queue_start_and_enqueue_are_idempotent(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "shared-queue.db"

    def enqueue(_):
        return (
            PersistentJobStore(path)
            .enqueue("local", "evidence", {"topic": "one"}, request_key="same-request")
            .id
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        identifiers = list(pool.map(enqueue, range(16)))
    assert len(set(identifiers)) == 1
    assert len(PersistentJobStore(path).list("local")) == 1


def test_orphan_preview_cleanup_preserves_active_uploads(tmp_path, monkeypatch):
    from src.services import document_previews as previews
    from src.services.storage import StorageQuotaService

    store = PersistentJobStore(tmp_path / "jobs.db")
    storage = StorageQuotaService(tmp_path / "storage")
    monkeypatch.setattr(previews, "get_storage_service", lambda: storage)
    active, orphan = "a" * 32, "b" * 32
    store.enqueue("local", "document_preview", {"preview_id": active})
    for identifier in (active, orphan):
        directory = previews.preview_directory("local", identifier)
        directory.mkdir(parents=True)
        (directory / "config.json").write_text("private")
        os.utime(directory, (1, 1))
    assert previews.cleanup_orphan_previews(store) == 1
    assert previews.preview_directory("local", active).exists()
    assert not previews.preview_directory("local", orphan).exists()


@pytest.mark.parametrize(
    "format,content_type,suffix",
    [
        ("markdown", "text/markdown", ".md"),
        ("text", "text/plain", ".txt"),
        ("json", "application/json", ".json"),
    ],
)
def test_study_exports_support_presenton_text_upload(
    tmp_path, monkeypatch, format, content_type, suffix
):
    from src.api.routers import learning as routes

    store = LearningStore(tmp_path / "learning.db")
    seed(store)
    monkeypatch.setattr(routes, "LearningStore", lambda: store)
    app = FastAPI()
    app.include_router(routes.router, prefix="/learning")
    response = TestClient(app).get("/learning/artifacts/pack/export", params={"format": format})
    assert response.status_code == 200
    assert content_type in response.headers["content-type"]
    assert suffix in response.headers["content-disposition"]
    assert "src_example" in response.text
    if format != "json":
        assert "https://github.com/presenton/presenton" in response.text


def test_local_huggingface_embedding_ignores_http_url_defaults(monkeypatch):
    from src.services import config as unified
    from src.services.embedding.config import get_embedding_config

    monkeypatch.setattr(
        unified,
        "get_active_embedding_config",
        lambda: {
            "provider": "huggingface",
            "model": "test-local",
            "base_url": "https://unused.example/v1",
            "dimensions": 3,
        },
    )
    assert get_embedding_config().base_url is None
    monkeypatch.setattr(unified, "get_active_embedding_config", lambda: None)
    monkeypatch.setenv("EMBEDDING_BINDING", "huggingface")
    monkeypatch.setenv("EMBEDDING_MODEL", "test-local")
    monkeypatch.setenv("EMBEDDING_HOST", "https://unused.example/v1")
    assert get_embedding_config().base_url is None
    monkeypatch.setenv("EMBEDDING_BINDING", "vllm")
    monkeypatch.setenv("EMBEDDING_API_KEY", "fixture")
    assert get_embedding_config().base_url == "https://unused.example/v1"


def test_legacy_local_indexes_remain_compatible_but_real_changes_require_reindex():
    from src.services.embedding.config import embedding_signatures_match

    old = {
        "provider": "huggingface",
        "model": "local",
        "dimensions": 3,
        "base_url": "https://unused.example/v1",
    }
    current = {**old, "base_url": None}
    assert embedding_signatures_match(old, current)
    assert old["base_url"] is not None
    assert not embedding_signatures_match(old, {**current, "dimensions": 4})
    assert not embedding_signatures_match(
        {**old, "provider": "openai"}, {**current, "provider": "openai"}
    )


@pytest.mark.asyncio
async def test_missing_index_message_is_not_published_as_evidence(tmp_path, monkeypatch):
    from src.services import config
    from src.services.learning import workflows
    from src.services.settings import fingerprint
    from src.tools import rag_tool

    store = LearningStore(tmp_path / "learning.db")
    monkeypatch.setattr(workflows, "LearningStore", lambda: store)
    monkeypatch.setattr(fingerprint, "model_fingerprint", lambda: "fixture")
    monkeypatch.setattr(
        config, "get_kb_config_service", lambda: SimpleNamespace(get_kb_config=lambda _: {})
    )

    async def no_index(**_):
        return {
            "answer": "No documents indexed. Please upload documents first.",
            "content": "",
            "provider": "llamaindex",
        }

    monkeypatch.setattr(rag_tool, "rag_search", no_index)
    sources = await workflows.collect_sources({"topic": "Unknown fact", "kb_name": "empty"})
    assert sources == [] and store.list("source") == []
