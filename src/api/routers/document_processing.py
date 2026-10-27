"""Workspace document parser settings and a bounded upload preview."""

from pathlib import Path
import tempfile

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.services.document_processing import (
    DocumentProcessingConfig,
    capabilities,
    parse_document,
    public_document_config,
    save_document_config,
)

router = APIRouter()


@router.get("")
async def get_settings():
    return {"config": public_document_config(), "presets": capabilities()}


@router.put("")
async def update_settings(config: DocumentProcessingConfig):
    try:
        return {"config": save_document_config(config)}
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/test")
async def test_document(file: UploadFile = File(...)):
    with tempfile.TemporaryDirectory(prefix="edunote-parser-") as directory:
        path = Path(directory) / ("input" + Path(file.filename or "input.pdf").suffix.lower())
        if path.suffix not in {".pdf", ".docx", ".pptx", ".png", ".jpg", ".jpeg", ".txt", ".md"}:
            raise HTTPException(422, "Unsupported preview file type")
        total = 0
        with path.open("wb") as stream:
            while chunk := await file.read(65536):
                total += len(chunk)
                if total > 20 * 1024 * 1024:
                    raise HTTPException(413, "Preview file limit is 20 MiB")
                stream.write(chunk)
        try:
            result = await parse_document(path, Path(directory) / "output")
        except Exception as error:
            raise HTTPException(422, str(error)) from error
        text = "\n\n".join(str(x.get("text", "")) for x in result["content_list"])
        return {
            "parser": result["parser"],
            "blocks": len(result["content_list"]),
            "preview": text[:4000],
            "warnings": result["warnings"],
        }
