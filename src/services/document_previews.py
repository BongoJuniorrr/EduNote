"""Durable parser previews with private, short-lived upload staging."""
import asyncio
from pathlib import Path
import re
import shutil

from src.services.document_processing import DocumentProcessingConfig, run_parser_process
from src.services.storage import get_storage_service


def preview_directory(owner_id: str, preview_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", preview_id):
        raise ValueError("Invalid document preview ID")
    return get_storage_service().safe_path(owner_id, f"document_previews/{preview_id}")


def run_document_preview(payload, job):
    directory = preview_directory(job.owner_id, str(payload.get("preview_id", "")))
    try:
        cfg = DocumentProcessingConfig.model_validate_json((directory / "config.json").read_text())
        files = list(directory.glob("input.*"))
        if len(files) != 1:
            raise ValueError("Preview upload is no longer available; upload the document again")
        return asyncio.run(run_parser_process(files[0], directory / "output", cfg))
    finally:
        shutil.rmtree(directory, ignore_errors=True)
