"""Transactional single-owner learning store, backed up with workspace storage."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import time

from src.services.storage import get_storage_service


class LearningStore:
    def __init__(self, path: Path | None = None):
        self.path = path or get_storage_service().safe_path("local", "learning/workspace.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        self.path.chmod(0o600)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, kind TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS cards(id TEXT PRIMARY KEY, pack_id TEXT NOT NULL, item TEXT NOT NULL, due REAL NOT NULL, interval REAL NOT NULL DEFAULT 0, ease REAL NOT NULL DEFAULT 2.5, repetitions INTEGER NOT NULL DEFAULT 0, lapses INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, card_id TEXT NOT NULL, answer INTEGER NOT NULL, correct INTEGER NOT NULL, rating INTEGER NOT NULL, created REAL NOT NULL, next_due REAL NOT NULL, explanation TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS cards_due ON cards(due);
            """)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, identifier: str, kind: str, body: dict):
        with self.connect() as db:
            # Fence artifact commits against cancellation and expired/reclaimed
            # leases. Lock queue state in the same short transaction as the write.
            worker = os.getenv("EDUNOTE_WORKER_ID")
            job_id = os.getenv("EDUNOTE_ACTIVE_JOB")
            if worker and job_id:
                from src.services.queue import get_job_store

                db.execute("ATTACH DATABASE ? AS queue_db", (str(get_job_store().path),))
                db.execute("BEGIN IMMEDIATE")
                active = db.execute(
                    "SELECT 1 FROM queue_db.jobs WHERE id=? AND status='running' AND lease_owner=? AND lease_expires>?",
                    (job_id, worker, time.time()),
                ).fetchone()
                if not active:
                    raise RuntimeError("Job was cancelled or its worker lease expired")
            db.execute(
                "INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?)",
                (identifier, kind, json.dumps(body, ensure_ascii=False), time.time()),
            )
        return self.get(identifier)

    def get(self, identifier: str):
        with self.connect() as db:
            row = db.execute("SELECT * FROM artifacts WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise LookupError("Artifact not found")
        return {
            "id": row["id"],
            "kind": row["kind"],
            "created_at": row["created"],
            **json.loads(row["body"]),
        }

    def list(self, kind: str):
        with self.connect() as db:
            rows = db.execute(
                "SELECT id, created FROM artifacts WHERE kind=? ORDER BY created DESC LIMIT 100",
                (kind,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "created_at": row["created"],
                "title": self.get(row["id"]).get("title", ""),
            }
            for row in rows
        ]

    def enroll(self, pack_id: str):
        pack = self.get(pack_id)
        if pack["kind"] != "study_pack":
            raise ValueError("Only study packs can be enrolled")
        with self.connect() as db:
            for index, item in enumerate(pack["pack"]["quiz"]):
                db.execute(
                    "INSERT OR IGNORE INTO cards(id,pack_id,item,due) VALUES(?,?,?,?)",
                    (f"{pack_id}:{index}", pack_id, json.dumps(item), time.time()),
                )
        return self.review()

    def review(self):
        now = time.time()
        with self.connect() as db:
            cards = db.execute("SELECT * FROM cards ORDER BY due LIMIT 500").fetchall()
            rows = db.execute(
                "SELECT a.*, c.item FROM attempts a JOIN cards c ON a.card_id=c.id ORDER BY a.created DESC LIMIT 500"
            ).fetchall()
        topics = {}
        for row in rows:
            topic = json.loads(row["item"])["topic"]
            value = topics.setdefault(topic, {"topic": topic, "attempts": 0, "correct": 0})
            value["attempts"] += 1
            value["correct"] += row["correct"]
        # Answers are returned only after submission; upcoming cards never leak them.
        return {
            "cards": [
                {
                    "id": row["id"],
                    "pack_id": row["pack_id"],
                    "due": row["due"],
                    "is_due": row["due"] <= now,
                    "repetitions": row["repetitions"],
                    "lapses": row["lapses"],
                    "item": {
                        k: v
                        for k, v in json.loads(row["item"]).items()
                        if k not in {"answer", "explanation"}
                    },
                }
                for row in cards
            ],
            "topics": list(topics.values()),
            "attempts": len(rows),
            "algorithm": "SM-2 inspired; Again 10 min, Hard 1 day, Good 1/6 days then ease multiplier, Easy 4 days then multiplier. Incorrect answers reset repetitions.",
        }

    def answer(self, card_id: str, answer: int, rating: int, request_id: str):
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM attempts WHERE id=?", (request_id,)).fetchone()
            if previous:
                if (
                    previous["card_id"] != card_id
                    or previous["answer"] != answer
                    or previous["rating"] != rating
                ):
                    raise ValueError("Attempt ID already used for a different submission")
                original_card = db.execute(
                    "SELECT item FROM cards WHERE id=?", (card_id,)
                ).fetchone()
                item = json.loads(original_card["item"])
                return {
                    "id": request_id,
                    "correct": bool(previous["correct"]),
                    "answer": item["answer"],
                    "explanation": previous["explanation"],
                    "source_ids": item["source_ids"],
                    "next_due": previous["next_due"],
                    "interval_days": (previous["next_due"] - previous["created"]) / 86400,
                }
            row = db.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
            if not row:
                raise LookupError("Review card not found")
            item = json.loads(row["item"])
            if not 0 <= answer < len(item["options"]) or rating not in range(4):
                raise ValueError("Invalid answer or review rating")
            if row["due"] > now:
                raise ValueError("This card is not due yet")
            correct = answer == item["answer"]
            effective = rating if correct else 0
            reps, ease = row["repetitions"], row["ease"]
            if effective == 0:
                interval, reps = 10 / 1440, 0
            elif effective == 1:
                interval, reps = max(1, row["interval"] * 1.2), reps + 1
            elif effective == 3:
                interval, reps = max(4, row["interval"] * (ease + 0.3)), reps + 1
            else:
                interval, reps = (
                    (1 if reps == 0 else 6 if reps == 1 else row["interval"] * ease),
                    reps + 1,
                )
            ease = max(1.3, ease + {0: -0.2, 1: -0.15, 2: 0, 3: 0.15}[effective])
            due = now + interval * 86400
            db.execute(
                "UPDATE cards SET due=?, interval=?, ease=?, repetitions=?, lapses=lapses+? WHERE id=?",
                (due, interval, ease, reps, int(not correct or effective == 0), card_id),
            )
            db.execute(
                "INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?)",
                (request_id, card_id, answer, int(correct), rating, now, due, item["explanation"]),
            )
        return {
            "id": request_id,
            "correct": correct,
            "answer": item["answer"],
            "explanation": item["explanation"],
            "source_ids": item["source_ids"],
            "next_due": due,
            "interval_days": interval,
        }

    def export(self):
        with self.connect() as db:
            return {
                "schema_version": 1,
                **{
                    table: [dict(row) for row in db.execute(f"SELECT * FROM {table}")]
                    for table in ("artifacts", "cards", "attempts")
                },
            }

    def import_backup(self, data: dict):
        """Merge a validated backup atomically; never overwrite newer local progress."""
        import math
        from typing import Literal

        from pydantic import BaseModel, ConfigDict, Field

        from src.services.learning.models import SourcedText, StudyPack

        class ArtifactRow(BaseModel):
            model_config = ConfigDict(extra="forbid")
            id: str = Field(min_length=1, max_length=100)
            kind: Literal["source", "evidence", "study_pack", "settings_diagnostics"]
            body: str = Field(max_length=1_000_000)
            created: float

        class CardRow(BaseModel):
            model_config = ConfigDict(extra="forbid")
            id: str = Field(min_length=1, max_length=150)
            pack_id: str = Field(min_length=1, max_length=100)
            item: str = Field(max_length=50_000)
            due: float
            interval: float = Field(ge=0, le=100_000)
            ease: float = Field(ge=1.3, le=100)
            repetitions: int = Field(ge=0)
            lapses: int = Field(ge=0)

        class AttemptRow(BaseModel):
            model_config = ConfigDict(extra="forbid")
            id: str = Field(min_length=1, max_length=100)
            card_id: str = Field(min_length=1, max_length=150)
            answer: int = Field(ge=0, le=5)
            correct: int = Field(ge=0, le=1)
            rating: int = Field(ge=0, le=3)
            created: float
            next_due: float
            explanation: str = Field(max_length=3000)

        if data.get("schema_version") != 1:
            raise ValueError("Unsupported learning backup schema")
        tables = {}
        for table, model in (
            ("artifacts", ArtifactRow),
            ("cards", CardRow),
            ("attempts", AttemptRow),
        ):
            rows = data.get(table)
            if not isinstance(rows, list) or len(rows) > 50_000:
                raise ValueError("Invalid or oversized backup table")
            tables[table] = [model.model_validate(row).model_dump() for row in rows]
            if any(
                isinstance(value, float) and not math.isfinite(value)
                for row in tables[table]
                for value in row.values()
            ):
                raise ValueError("Backup contains invalid numeric values")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in tables["artifacts"]:
                body = json.loads(row["body"])
                if not isinstance(body, dict):
                    raise ValueError("Invalid artifact body")
                if row["kind"] in {"evidence", "study_pack"}:
                    sources = body.get("sources")
                    if (
                        not isinstance(sources, list)
                        or len(sources) > 100
                        or not isinstance(body.get("title"), str)
                    ):
                        raise ValueError("Invalid sourced artifact")
                    for source in sources:
                        if (
                            not isinstance(source, dict)
                            or not isinstance(source.get("id"), str)
                            or not isinstance(source.get("text"), str)
                            or not isinstance(source.get("provenance", {}), dict)
                        ):
                            raise ValueError("Invalid source snapshot")
                    allowed = {source["id"] for source in sources}
                    if row["kind"] == "study_pack":
                        StudyPack.model_validate(body["pack"]).validate_sources(allowed)
                    else:
                        if body.get("status") not in {
                            "grounded",
                            "no_evidence",
                            "insufficient_evidence",
                        } or not isinstance(body.get("claims"), list):
                            raise ValueError("Invalid evidence result")
                        for claim in body["claims"]:
                            if not set(SourcedText.model_validate(claim).source_ids) <= allowed:
                                raise ValueError("Evidence cites a missing source")
                elif row["kind"] == "source":
                    if body.get("id") != row["id"] or not isinstance(body.get("text"), str):
                        raise ValueError("Invalid source snapshot")
                elif row["kind"] == "settings_diagnostics":
                    checks = body.get("checks")
                    if (
                        not isinstance(checks, list)
                        or len(checks) > 8
                        or any(
                            not isinstance(check, dict)
                            or check.get("status") not in {"passed", "failed"}
                            for check in checks
                        )
                    ):
                        raise ValueError("Invalid diagnostics result")
            for table, rows in tables.items():
                for row in rows:
                    existing = db.execute(
                        f"SELECT * FROM {table} WHERE id=?", (row["id"],)
                    ).fetchone()
                    if existing:
                        if dict(existing) != row:
                            raise ValueError(
                                "Backup conflicts with current data; no changes were imported"
                            )
                        continue
                    if table == "cards":
                        pack_row = db.execute(
                            "SELECT kind,body FROM artifacts WHERE id=?", (row["pack_id"],)
                        ).fetchone()
                        if not pack_row or pack_row["kind"] != "study_pack":
                            raise ValueError("Review card references a missing study pack")
                        quiz = json.loads(pack_row["body"])["pack"]["quiz"]
                        if json.loads(row["item"]) not in quiz:
                            raise ValueError("Review card does not match its study pack")
                    if (
                        table == "attempts"
                        and not db.execute(
                            "SELECT 1 FROM cards WHERE id=?", (row["card_id"],)
                        ).fetchone()
                    ):
                        raise ValueError("Attempt references a missing review card")
                    columns = list(row)
                    db.execute(
                        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                        list(row.values()),
                    )
        return {"imported": {table: len(rows) for table, rows in tables.items()}}
