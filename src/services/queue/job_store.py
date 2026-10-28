"""SQLite-backed durable FIFO queue for the personal workspace."""

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time


@dataclass(frozen=True)
class Job:
    id: str
    owner_id: str
    kind: str
    priority: int
    status: str
    progress: int
    payload: dict
    result: dict | None
    error: str | None
    created_at: int
    updated_at: int


class PersistentJobStore:
    def __init__(self, path: Path | None = None):
        configured = os.getenv("EDUNOTE_QUEUE_DB", "")
        self.path = path or (
            Path(configured)
            if configured
            else Path(__file__).resolve().parents[3] / "data" / "edunote_queue.sqlite3"
        )
        self.path = self.path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            # Polling must remain readable while a worker commits status or a
            # heartbeat. Keep SQLite's default FULL synchronous durability.
            connection.execute("PRAGMA journal_mode = WAL")
            # API and worker can start together; serialize schema inspection
            # and ALTER statements so concurrent first starts cannot race.
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    payload TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)")}
            if "result" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN result TEXT")
            for column, definition in (
                ("lease_owner", "TEXT"),
                ("lease_expires", "REAL"),
                ("attempts", "INTEGER NOT NULL DEFAULT 0"),
                ("request_key", "TEXT"),
            ):
                if column not in columns:
                    connection.execute(f"ALTER TABLE jobs ADD COLUMN {column} {definition}")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_request ON jobs(owner_id,kind,request_key) WHERE request_key IS NOT NULL"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_ready ON jobs(status, priority DESC, created_at ASC)"
            )

    def enqueue(
        self,
        owner_id: str,
        kind: str,
        payload: dict,
        rank: str = "free",
        request_key: str | None = None,
    ) -> Job:
        if not owner_id or not kind:
            raise ValueError("owner_id and kind are required")
        now = int(time.time())
        job_id = f"job_{secrets.token_urlsafe(16)}"
        with self._connect() as connection:
            if request_key:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM jobs WHERE owner_id=? AND kind=? AND request_key=?",
                    (owner_id, kind, request_key),
                ).fetchone()
                if existing:
                    if json.loads(existing["payload"]) != payload:
                        raise ValueError(
                            "Request ID was already used with a different configuration or input"
                        )
                    return self._from_row(existing)
            connection.execute(
                "INSERT INTO jobs (id, owner_id, kind, priority, status, payload, created_at, updated_at, request_key) "
                "VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?)",
                (job_id, owner_id, kind, 0, json.dumps(payload), now, now, request_key),
            )
        return self.get(job_id, owner_id)

    def list(self, owner_id: str | None, limit: int = 100) -> list[Job]:
        with self._connect() as connection:
            if owner_id is None:
                rows = connection.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (min(max(limit, 1), 200),),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM jobs WHERE owner_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (owner_id, min(max(limit, 1), 200)),
                ).fetchall()
        return [self._from_row(row) for row in rows]

    def cancel(self, job_id: str, owner_id: str) -> Job:
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status = 'cancelled', updated_at = ? WHERE id = ? AND owner_id = ? AND status IN ('queued', 'running')",
                (int(time.time()), job_id, owner_id),
            )
        return self.get(job_id, owner_id)

    def claim_next(self, worker_id: str = "legacy", lease_seconds: float = 60) -> Job | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = time.time()
            # Abandoned work is retried at most three times. A legacy running
            # row without a lease gets a five-minute migration grace period.
            connection.execute(
                "UPDATE jobs SET status = CASE WHEN attempts >= 3 THEN 'failed' ELSE 'queued' END, "
                "error = CASE WHEN attempts >= 3 THEN 'Worker lease expired after three attempts' ELSE NULL END, "
                "lease_owner = NULL, lease_expires = NULL, updated_at = ? "
                "WHERE status = 'running' AND (lease_expires <= ? OR (lease_expires IS NULL AND updated_at <= ?))",
                (int(now), now, int(now) - 300),
            )
            row = connection.execute(
                "SELECT * FROM jobs WHERE status = 'queued' ORDER BY created_at ASC, rowid ASC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            now = int(time.time())
            connection.execute(
                "UPDATE jobs SET status = 'running', updated_at = ?, lease_owner = ?, lease_expires = ?, attempts = attempts + 1 "
                "WHERE id = ? AND status = 'queued'",
                (now, worker_id, time.time() + lease_seconds, row["id"]),
            )
            updated = connection.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()
        return self._from_row(updated)

    def update(
        self,
        job_id: str,
        status: str | None = None,
        progress: int | None = None,
        error: str | None = None,
        result: dict | None = None,
        worker_id: str | None = None,
    ) -> Job:
        allowed_statuses = {"queued", "running", "completed", "failed", "cancelled"}
        if status is not None and status not in allowed_statuses:
            raise ValueError("Invalid job status")
        if progress is not None and not 0 <= progress <= 100:
            raise ValueError("progress must be between 0 and 100")
        updates: list[str] = ["updated_at = ?"]
        values: list[object] = [int(time.time())]
        if status is not None:
            updates.append("status = ?")
            values.append(status)
        if progress is not None:
            updates.append("progress = ?")
            values.append(progress)
        if error is not None:
            updates.append("error = ?")
            values.append(error[:2000])
        if result is not None:
            updates.append("result = ?")
            values.append(json.dumps(result))
        values.append(job_id)
        predicate = "id = ?"
        if worker_id is not None:
            predicate += " AND status = 'running' AND lease_owner = ? AND lease_expires > ?"
            values.extend([worker_id, time.time()])
        with self._connect() as connection:
            result = connection.execute(
                f"UPDATE jobs SET {', '.join(updates)} WHERE {predicate}", values
            )
            if result.rowcount != 1 and worker_id is None:
                raise LookupError("Job not found")
        return self.get(job_id)

    def owns_lease(self, job_id: str, worker_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM jobs WHERE id=? AND status='running' AND lease_owner=? AND lease_expires>?",
                (job_id, worker_id, time.time()),
            ).fetchone()
        return bool(row)

    def renew_lease(self, job_id: str, worker_id: str, lease_seconds: float = 60) -> bool:
        now = time.time()
        with self._connect() as connection:
            return (
                connection.execute(
                    "UPDATE jobs SET lease_expires = ?, updated_at = ? WHERE id = ? "
                    "AND status = 'running' AND lease_owner = ? AND lease_expires > ?",
                    (now + lease_seconds, int(now), job_id, worker_id, now),
                ).rowcount
                == 1
            )

    def get(self, job_id: str, owner_id: str | None = None) -> Job:
        with self._connect() as connection:
            if owner_id is None:
                row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM jobs WHERE id = ? AND owner_id = ?", (job_id, owner_id)
                ).fetchone()
        if not row:
            raise LookupError("Job not found")
        return self._from_row(row)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            owner_id=row["owner_id"],
            kind=row["kind"],
            priority=row["priority"],
            status=row["status"],
            progress=row["progress"],
            payload=json.loads(row["payload"]),
            result=json.loads(row["result"]) if row["result"] else None,
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


_job_store: PersistentJobStore | None = None


def get_job_store() -> PersistentJobStore:
    global _job_store
    if _job_store is None:
        _job_store = PersistentJobStore()
    return _job_store
