from pathlib import Path

import pytest

from src.services.queue.gpu import GpuResourceManager
from src.services.queue.job_store import PersistentJobStore
from src.services.queue.worker import QueueWorker


def test_queue_is_fifo_regardless_of_legacy_rank(tmp_path: Path):
    store = PersistentJobStore(tmp_path / "queue.sqlite3")
    low = store.enqueue("user-a", "tts", {"text": "low"}, rank="free")
    high = store.enqueue("user-b", "tts", {"text": "high"}, rank="pro")

    claimed = store.claim_next()

    assert claimed.id == low.id
    assert claimed.status == "running"
    assert store.get(high.id, "user-b").status == "queued"


def test_queue_owner_isolation_and_state_validation(tmp_path: Path):
    store = PersistentJobStore(tmp_path / "queue.sqlite3")
    job = store.enqueue("user-a", "embedding", {})

    with pytest.raises(LookupError):
        store.get(job.id, "user-b")
    with pytest.raises(ValueError):
        store.update(job.id, progress=101)

    completed = store.update(job.id, status="completed", progress=100)
    assert completed.status == "completed"


def test_worker_completes_registered_handler_and_fails_unknown_kind(tmp_path: Path):
    store = PersistentJobStore(tmp_path / "queue.sqlite3")
    seen = []
    worker = QueueWorker(store)
    worker.register("test", lambda payload, job: {"value": seen.append(payload["value"])})

    store.enqueue("user-a", "test", {"value": 42})
    store.enqueue("user-a", "missing", {})

    first = worker.run_once()
    second = worker.run_once()

    assert first.status == "completed"
    assert second.status == "failed"
    assert seen == [42]
    assert first.result == {"value": None}


def test_gpu_manager_releases_file_lock_without_gpu(tmp_path: Path, monkeypatch):
    manager = GpuResourceManager(tmp_path / "gpu.lock")
    monkeypatch.setattr(manager, "_device_count", lambda: 0)

    with pytest.raises(TimeoutError):
        manager.acquire(timeout_seconds=0)

    assert manager._lock_handle is None


def test_async_gpu_handler_keeps_lease_until_completion(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src.services.queue import worker as module

    held = []

    class Lease:
        def __enter__(self):
            held.append(True)
            return SimpleNamespace(index=0)

        def __exit__(self, *args):
            held.clear()

    monkeypatch.setattr(module, "GpuResourceManager", Lease)
    store = PersistentJobStore(tmp_path / "queue.sqlite3")
    worker = QueueWorker(store)

    async def handle(payload, job):
        assert held and payload["gpu_index"] == 0
        return {"ok": True}

    worker.register("gpu", handle, requires_gpu=True)
    store.enqueue("local", "gpu", {})
    assert worker.run_once().result == {"ok": True}
    assert not held


def test_expired_worker_lease_recovers_and_old_worker_cannot_commit(tmp_path, monkeypatch):
    from src.services.queue import job_store as module
    clock = [1000.0]
    monkeypatch.setattr(module.time, 'time', lambda: clock[0])
    store = PersistentJobStore(tmp_path / 'lease.sqlite3')
    job = store.enqueue('local', 'retrieve', {})
    assert store.claim_next('crashed', 10).id == job.id
    clock[0] += 11
    assert store.claim_next('replacement', 10).id == job.id
    old = store.update(job.id, status='completed', result={'stale': True}, worker_id='crashed')
    assert old.status == 'running' and old.result is None
    assert store.update(job.id, status='completed', result={'ok': True}, worker_id='replacement').result == {'ok': True}


def test_lease_renewal_prevents_duplicate_claim_and_cancellation_wins(tmp_path, monkeypatch):
    from src.services.queue import job_store as module
    clock = [1000.0]
    monkeypatch.setattr(module.time, 'time', lambda: clock[0])
    store = PersistentJobStore(tmp_path / 'lease.sqlite3')
    job = store.enqueue('local', 'retrieve', {})
    store.claim_next('active', 10)
    clock[0] += 8
    assert store.renew_lease(job.id, 'active', 10)
    clock[0] += 5
    assert store.claim_next('other', 10) is None
    store.update(job.id, status='cancelled')
    assert not store.renew_lease(job.id, 'active', 10)
    assert store.update(job.id, status='completed', worker_id='active').status == 'cancelled'


def test_repeated_worker_crashes_fail_instead_of_retrying_forever(tmp_path, monkeypatch):
    from src.services.queue import job_store as module
    clock = [1000.0]
    monkeypatch.setattr(module.time, 'time', lambda: clock[0])
    store = PersistentJobStore(tmp_path / 'lease.sqlite3')
    job = store.enqueue('local', 'retrieve', {})
    for attempt in range(3):
        assert store.claim_next(str(attempt), 10).id == job.id
        clock[0] += 11
    assert store.claim_next('final', 10) is None
    assert store.get(job.id).status == 'failed'
