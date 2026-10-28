"""Single-owner learning APIs: durable evidence, sourced packs and review."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from src.security.auth import get_current_user
from src.services.learning.store import LearningStore
from src.services.queue import get_job_store

router = APIRouter(dependencies=[Depends(get_current_user)])


class EvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(min_length=3, max_length=3000)
    kb_name: str | None = Field(default=None, max_length=150)
    notebook_id: str | None = Field(default=None, max_length=100)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class PackRequest(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class DiagnosticRequest(BaseModel):
    checks: list[
        Literal[
            "runtime", "text", "multiturn", "json", "vision", "embedding", "parser", "presenton"
        ]
    ] = Field(min_length=1, max_length=8)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class AttemptRequest(BaseModel):
    answer: int = Field(ge=0, le=5)
    rating: int = Field(ge=0, le=3)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


def enqueue(kind, payload, request_id):
    from src.services.settings.fingerprint import workflow_fingerprint

    try:
        payload["config_fingerprint"] = workflow_fingerprint()
        job = get_job_store().enqueue("local", kind, payload, request_key=request_id)
        return {"job": job.__dict__}
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


def artifact(identifier):
    try:
        return LearningStore().get(identifier)
    except LookupError as error:
        raise HTTPException(404, "Artifact not found") from error


@router.post("/evidence", status_code=202)
def create_evidence(request: EvidenceRequest):
    if not request.kb_name and not request.notebook_id:
        raise HTTPException(422, "Select a knowledge base or notebook")
    if request.kb_name:
        from src.services.rag.service import DEFAULT_KB_BASE_DIR

        root = Path(DEFAULT_KB_BASE_DIR).resolve()
        # Resolve an identifier against the server-owned catalog. Never construct
        # a filesystem path from a request string, including before validation.
        entries = root.iterdir() if root.is_dir() else ()
        selected = next(
            (entry for entry in entries
             if entry.name == request.kb_name and not entry.is_symlink() and entry.is_dir()),
            None,
        )
        if selected is None:
            raise HTTPException(422, "Knowledge base not found")
        request.kb_name = selected.name
    if request.notebook_id:
        from src.api.utils.notebook_manager import notebook_manager

        try:
            notebook = notebook_manager.get_notebook(request.notebook_id)
        except ValueError as error:
            raise HTTPException(422, "Invalid notebook ID") from error
        if not notebook:
            raise HTTPException(422, "Notebook not found")
    return enqueue("evidence", request.model_dump(exclude={"request_id"}), request.request_id)


@router.post("/study-packs", status_code=202)
def create_pack(request: PackRequest):
    value = artifact(request.evidence_id)
    if value["kind"] != "evidence" or not value.get("sources"):
        raise HTTPException(422, "Select evidence with retrieved sources")
    return enqueue("study_pack", {"evidence_id": request.evidence_id}, request.request_id)


@router.post("/diagnostics", status_code=202)
def diagnostics(request: DiagnosticRequest):
    return enqueue(
        "settings_diagnostics", {"checks": list(dict.fromkeys(request.checks))}, request.request_id
    )


@router.get("/artifacts")
def list_artifacts(kind: Literal["evidence", "study_pack", "settings_diagnostics"] = "evidence"):
    return {"artifacts": LearningStore().list(kind)}


@router.get("/artifacts/{identifier}")
def get_artifact(identifier: str):
    return artifact(identifier)


@router.get("/artifacts/{identifier}/export")
def export_artifact(identifier: str, format: Literal["json", "markdown", "text"] = "json"):
    value = artifact(identifier)
    if format == "json":
        return Response(
            json.dumps(value, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="edunote-artifact.json"'},
        )
    lines = ["# " + value.get("title", "EduNote"), ""]
    if value["kind"] == "study_pack":
        for section in ("goals", "summary", "concepts", "quiz", "rubric"):
            lines += ["## " + section.title(), ""]
            for item in value["pack"][section]:
                lines.append(
                    "- " + item["text"] + " " + " ".join(f"[{sid}]" for sid in item["source_ids"])
                )
                if section == "quiz":
                    lines += [f"  {i + 1}. {option}" for i, option in enumerate(item["options"])]
                    lines += [f"  Answer: {item['answer'] + 1}. {item['explanation']}"]
        lines += [
            "",
            value.get(
                "slides_attribution",
                "Slides powered by Presenton: https://github.com/presenton/presenton",
            ),
        ]
    else:
        lines += [
            item["text"] + " " + " ".join(f"[{sid}]" for sid in item["source_ids"])
            for item in value.get("claims", [])
        ]
    lines += ["", "## Sources", ""]
    for source in value.get("sources", []):
        lines += [
            f"### {source['id']}: {source.get('doc_name') or 'Index excerpt'} (page {source.get('page_start') or 'unknown'})",
            source["text"],
            "",
        ]
    return Response(
        "\n".join(lines),
        media_type="text/plain" if format == "text" else "text/markdown",
        headers={
            "Content-Disposition": 'attachment; filename="edunote-study-pack.txt"'
            if format == "text"
            else 'attachment; filename="edunote-study-pack.md"'
        },
    )


@router.get("/sources/{identifier}/document")
def get_source_document(identifier: str):
    source = artifact(identifier)
    if source["kind"] != "source" or not source.get("kb_name") or not source.get("doc_name"):
        raise HTTPException(404, "This excerpt has no original document link")
    from src.services.rag.service import DEFAULT_KB_BASE_DIR

    root = Path(DEFAULT_KB_BASE_DIR).resolve()
    kb = (root / source["kb_name"]).resolve()
    raw = (kb / "raw").resolve()
    path = (raw / source["doc_name"]).resolve()
    if kb.parent != root or raw.parent != kb or path.parent != raw or not path.is_file():
        raise HTTPException(404, "Original document is unavailable")
    if source.get("document_sha256"):
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != source["document_sha256"]:
            raise HTTPException(
                409, "Original document changed since retrieval. Retrieve fresh evidence."
            )
    if path.suffix.lower() != ".pdf":
        return FileResponse(path, filename=path.name, content_disposition_type="attachment")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.post("/study-packs/{identifier}/review")
def enroll(identifier: str):
    try:
        return LearningStore().enroll(identifier)
    except LookupError as error:
        raise HTTPException(404, "Study pack not found") from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/review")
def review():
    return LearningStore().review()


@router.post("/review/{card_id}/answer")
def answer(card_id: str, request: AttemptRequest):
    try:
        return LearningStore().answer(card_id, request.answer, request.rating, request.request_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.get("/export")
def export_learning():
    return Response(
        json.dumps(LearningStore().export(), ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="edunote-learning-backup.json"'},
    )


@router.post("/import")
async def import_learning(request: Request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 20 * 1024 * 1024:
            raise HTTPException(413, "Learning backup limit is 20 MiB")
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Backup must be a JSON object")
        return LearningStore().import_backup(data)
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(
            422,
            "Invalid learning backup or conflicts with current progress. No data was overwritten.",
        ) from error
