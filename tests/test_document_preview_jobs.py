import asyncio
import os
from pathlib import Path
import sys
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.api.routers import document_processing as routes
from src.services import document_processing as docs, document_previews as previews
from src.services.queue import PersistentJobStore, QueueWorker
from src.services.storage import StorageQuotaService


@pytest.fixture
def setup(tmp_path, monkeypatch):
    store = PersistentJobStore(tmp_path / "jobs.sqlite3")
    storage = StorageQuotaService(tmp_path / "storage")
    monkeypatch.setattr(routes, "get_job_store", lambda: store)
    monkeypatch.setattr(previews, "get_storage_service", lambda: storage)
    monkeypatch.setattr(docs, "SETTINGS_PATH", tmp_path / "settings.json")
    docs.save_document_config(docs.DocumentProcessingConfig(parser="pymupdf", api_key="private-preview-key"))
    app = FastAPI()
    app.include_router(routes.router, prefix="/documents")
    return TestClient(app), store, storage


def enqueue(client, name="sample.txt", data=b"Document preview regression"):
    return client.post("/documents/test?background=true", files={"file": (name, data)})


def test_background_preview_survives_store_reload_and_cleans_private_staging(setup):
    client, store, storage = setup
    response = enqueue(client)
    assert response.status_code == 202
    test_id = response.json()["test_id"]
    job = store.get(test_id)
    assert job.status == "queued"
    assert set(job.payload) == {"preview_id"}
    directory = previews.preview_directory(job.owner_id, job.payload["preview_id"])
    assert (directory / "config.json").stat().st_mode & 0o777 == 0o600
    assert "private-preview-key" not in response.text
    # The queued operation uses the saved snapshot even if settings change.
    docs.save_document_config(docs.DocumentProcessingConfig(parser="vision", base_url="http://example.invalid", model="unavailable"))
    worker = QueueWorker(PersistentJobStore(store.path))
    worker.register("document_preview", previews.run_document_preview)
    assert worker.run_once().status == "completed"
    state = client.get(f"/documents/tests/{test_id}").json()
    assert state["status"] == "completed"
    assert state["result"]["preview"] == "Document preview regression"
    assert "private-preview-key" not in str(state)
    assert not directory.exists()


def test_parser_failure_is_pollable_and_removes_upload(setup):
    client, store, _ = setup
    test_id = enqueue(client, "broken.pdf", b"not a pdf").json()["test_id"]
    job = store.get(test_id)
    directory = previews.preview_directory(job.owner_id, job.payload["preview_id"])
    worker = QueueWorker(store)
    worker.register("document_preview", previews.run_document_preview)
    assert worker.run_once().status == "failed"
    state = client.get(f"/documents/tests/{test_id}").json()
    assert state["status"] == "failed" and state["error"]
    assert "private-preview-key" not in state["error"]
    assert not directory.exists()
    assert client.get("/documents").status_code == 200


@pytest.mark.parametrize("name,data,code", [("bad.exe", b"x", 422), ("large.txt", b"x" * (20 * 1024 * 1024 + 1), 413)])
def test_rejected_uploads_do_not_leave_staging(setup, name, data, code):
    client, _, storage = setup
    assert enqueue(client, name, data).status_code == code
    assert not list(storage.root.glob("document_previews/*"))


def test_document_status_does_not_expose_other_job_types(setup):
    client, store, _ = setup
    assert client.get("/documents/tests/missing").status_code == 404
    from src.security.auth import LOCAL_USER
    job = store.enqueue(LOCAL_USER.id, "tts", {"secret": "private"})
    assert client.get(f"/documents/tests/{job.id}").status_code == 404
    with pytest.raises(ValueError):
        previews.preview_directory(LOCAL_USER.id, "../../outside")


def test_parser_child_has_clean_import_path(tmp_path, monkeypatch):
    root = Path(docs.__file__).resolve().parents[2]
    monkeypatch.setenv("PYTHONPATH", str(root / "src"))
    monkeypatch.syspath_prepend(str(root / "src"))
    path = tmp_path / "sample.txt"
    path.write_text("Clean logging imports")
    result = asyncio.run(docs.run_parser_process(path, tmp_path / "output", docs.DocumentProcessingConfig(parser="pymupdf")))
    assert result["preview"] == "Clean logging imports"


def test_parser_timeout_reaps_process_group(tmp_path, monkeypatch):
    real_spawn = asyncio.create_subprocess_exec
    children = []

    async def spawn(*args, **kwargs):
        child = await real_spawn(sys.executable, "-c", "import time; time.sleep(30)", **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    cfg = docs.DocumentProcessingConfig().model_copy(update={"timeout_seconds": 0.1})
    with pytest.raises(ValueError, match="timed out"):
        asyncio.run(docs.run_parser_process(tmp_path / "input.pdf", tmp_path / "out", cfg))
    assert children[0].returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(children[0].pid, 0)


def test_worker_health_heartbeat_continues_during_parser_job(tmp_path, monkeypatch):
    heartbeat = tmp_path / "heartbeat"
    monkeypatch.setenv("EDUNOTE_QUEUE_HEARTBEAT", str(heartbeat))
    worker = QueueWorker(PersistentJobStore(tmp_path / "jobs.sqlite3"))
    worker.lease_seconds = 0.3
    worker.store.enqueue("owner", "long_parser", {})

    def handler(payload, job):
        deadline = time.monotonic() + 2
        while not heartbeat.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert heartbeat.exists()
        return {"alive": True}

    worker.register("long_parser", handler)
    assert worker.run_once().status == "completed"
