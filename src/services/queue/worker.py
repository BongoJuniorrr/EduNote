"""Durable queue worker lifecycle."""

import asyncio
import inspect
import logging
import os
import time
import threading
import uuid
from typing import Any, Callable
from pathlib import Path

from .gpu import GpuResourceManager
from .job_store import Job, PersistentJobStore, get_job_store

logger = logging.getLogger(__name__)


class QueueWorker:
    def __init__(self, store: PersistentJobStore | None = None):
        self.store = store or get_job_store()
        self.worker_id = uuid.uuid4().hex
        self.lease_seconds = 60
        self.handlers: dict[str, tuple[Callable[[dict, Job], Any], bool]] = {}

    def register(
        self, kind: str, handler: Callable[[dict, Job], Any], requires_gpu: bool = False
    ) -> None:
        self.handlers[kind] = (handler, requires_gpu)

    def run_once(self) -> Job | None:
        job = self.store.claim_next(self.worker_id, self.lease_seconds)
        if job is None:
            return None
        handler_config = self.handlers.get(job.kind)
        if handler_config is None:
            self.store.update(
                job.id, status="failed", error=f"No handler registered for {job.kind}", worker_id=self.worker_id
            )
            return self.store.get(job.id)
        handler, requires_gpu = handler_config
        stopped = threading.Event()

        def heartbeat():
            while not stopped.wait(self.lease_seconds / 3):
                try:
                    if not self.store.renew_lease(job.id, self.worker_id, self.lease_seconds):
                        return
                    Path(os.getenv("EDUNOTE_QUEUE_HEARTBEAT", "/tmp/edunote-worker-heartbeat")).touch()
                except Exception:
                    logger.exception("Could not renew queue lease")

        renewal = threading.Thread(target=heartbeat, daemon=True)
        renewal.start()
        try:
            lease_manager = GpuResourceManager() if requires_gpu else None
            if lease_manager:
                with lease_manager as lease:
                    result = handler({**job.payload, "gpu_index": lease.index}, job)
                    if inspect.isawaitable(result):
                        result = asyncio.run(result)
            else:
                result = handler(job.payload, job)
            if inspect.isawaitable(result):
                result = asyncio.run(result)
            return self.store.update(
                job.id,
                status="completed",
                progress=100,
                result=result if isinstance(result, dict) else None,
                worker_id=self.worker_id,
            )
        except Exception as error:
            logger.exception("Queue job failed: %s", job.id)
            return self.store.update(job.id, status="failed", error=str(error), worker_id=self.worker_id)
        finally:
            stopped.set()
            renewal.join(timeout=6)

    def run_forever(self, poll_seconds: float = 1.0) -> None:
        heartbeat = Path(os.getenv("EDUNOTE_QUEUE_HEARTBEAT", "/tmp/edunote-worker-heartbeat"))
        heartbeat.parent.mkdir(parents=True, exist_ok=True)
        while True:
            heartbeat.touch()
            processed = self.run_once()
            if processed is None:
                time.sleep(poll_seconds)


def run_worker() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    QueueWorker().run_forever()


__all__ = ["QueueWorker", "run_worker"]
