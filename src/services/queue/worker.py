"""Durable queue worker lifecycle."""

import asyncio
import inspect
import json
import logging
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable
import uuid

from .gpu import GpuResourceManager
from .job_store import Job, PersistentJobStore, get_job_store

logger = logging.getLogger(__name__)


class QueueWorker:
    def __init__(self, store: PersistentJobStore | None = None):
        self.store = store or get_job_store()
        self.worker_id = uuid.uuid4().hex
        self.lease_seconds = 60
        self.isolated: set[str] = set()
        self.handlers: dict[str, tuple[Callable[[dict, Job], Any], bool]] = {}

    def register(
        self,
        kind: str,
        handler: Callable[[dict, Job], Any],
        requires_gpu: bool = False,
        isolated: bool = False,
    ) -> None:
        self.handlers[kind] = (handler, requires_gpu)
        if isolated:
            self.isolated.add(kind)

    def run_once(self) -> Job | None:
        job = self.store.claim_next(self.worker_id, self.lease_seconds)
        if job is None:
            return None
        handler_config = self.handlers.get(job.kind)
        if handler_config is None:
            self.store.update(
                job.id,
                status="failed",
                error=f"No handler registered for {job.kind}",
                worker_id=self.worker_id,
            )
            return self.store.get(job.id)
        handler, requires_gpu = handler_config
        stopped = threading.Event()

        def heartbeat():
            while not stopped.wait(self.lease_seconds / 3):
                try:
                    if not self.store.renew_lease(job.id, self.worker_id, self.lease_seconds):
                        return
                    Path(
                        os.getenv("EDUNOTE_QUEUE_HEARTBEAT", "/tmp/edunote-worker-heartbeat")
                    ).touch()
                except Exception:
                    logger.exception("Could not renew queue lease")

        renewal = threading.Thread(target=heartbeat, daemon=True)
        renewal.start()
        try:
            if job.kind in self.isolated:
                result = self._run_isolated(job)
                return self.store.update(
                    job.id,
                    status="completed",
                    progress=100,
                    result=result,
                    worker_id=self.worker_id,
                )
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
            return self.store.update(
                job.id, status="failed", error=str(error), worker_id=self.worker_id
            )
        finally:
            stopped.set()
            renewal.join(timeout=6)

    def _run_isolated(self, job: Job) -> dict:
        # Fresh interpreter: no inherited polluted imports or thread/CUDA state.
        with tempfile.TemporaryDirectory(prefix="edunote-job-") as directory:
            result_path = Path(directory) / "result.json"
            root = Path(__file__).resolve().parents[3]
            process = subprocess.Popen(
                [sys.executable, "-m", "src.services.queue.execute", job.id, str(result_path)],
                cwd=root,
                env={
                    **os.environ,
                    "PYTHONPATH": str(root),
                    "EDUNOTE_QUEUE_DB": str(self.store.path),
                    "EDUNOTE_WORKER_ID": self.worker_id,
                },
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                while process.poll() is None:
                    current = self.store.get(job.id)
                    if current.status != "running" or not self.store.owns_lease(
                        job.id, self.worker_id
                    ):
                        self._terminate_tree(process)
                        return {}
                    time.sleep(0.2)
                if not result_path.exists():
                    raise RuntimeError(
                        "Job process exited unexpectedly; check runtime availability"
                    )
                value = json.loads(result_path.read_text())
                if "error" in value:
                    raise RuntimeError(value["error"])
                return value.get("result", {})
            finally:
                if process.poll() is None:
                    self._terminate_tree(process)
                if job.kind == "document_preview":
                    import shutil

                    from src.services.document_previews import preview_directory

                    shutil.rmtree(
                        preview_directory(job.owner_id, job.payload["preview_id"]),
                        ignore_errors=True,
                    )

    @staticmethod
    def _terminate_tree(process):
        # Parser subprocesses may own separate sessions. Collect all descendants
        # before stopping the parent so none survive an explicit cancellation.
        descendants = {process.pid}
        while True:
            for pid in descendants:
                try:
                    os.kill(pid, signal.SIGSTOP)
                except ProcessLookupError:
                    pass
            parents = {}
            for entry in Path("/proc").iterdir():
                if entry.name.isdigit():
                    try:
                        stat = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                        parents[int(entry.name)] = int(stat[1])
                    except (OSError, ValueError, IndexError):
                        pass
            expanded = descendants | {
                pid for pid, parent in parents.items() if parent in descendants
            }
            if expanded == descendants:
                break
            descendants = expanded
        for pid in descendants:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=10)

    def run_forever(self, poll_seconds: float = 1.0) -> None:
        heartbeat = Path(os.getenv("EDUNOTE_QUEUE_HEARTBEAT", "/tmp/edunote-worker-heartbeat"))
        heartbeat.parent.mkdir(parents=True, exist_ok=True)
        last_cleanup = 0.0
        while True:
            heartbeat.touch()
            try:
                if time.monotonic() - last_cleanup > 900:
                    from src.services.document_previews import cleanup_orphan_previews

                    try:
                        cleanup_orphan_previews(self.store)
                    except (OSError, ValueError):
                        logger.warning("Could not clean expired preview staging; retrying later")
                    last_cleanup = time.monotonic()
                processed = self.run_once()
            except sqlite3.OperationalError as error:
                if "locked" not in str(error).lower() and "busy" not in str(error).lower():
                    raise
                logger.warning("Queue database is busy; retrying on the next poll")
                processed = None
            if processed is None:
                time.sleep(poll_seconds)


def run_worker() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    QueueWorker().run_forever()


__all__ = ["QueueWorker", "run_worker"]
