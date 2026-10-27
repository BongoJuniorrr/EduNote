import os
from typing import Annotated, List, Optional
from fastapi import APIRouter, Body, File, HTTPException, UploadFile
import logging

from constants.documents import UPLOAD_ACCEPTED_FILE_TYPES
from models.decomposed_file_info import DecomposedFileInfo
from services.temp_file_service import TEMP_FILE_SERVICE
from services.documents_loader import DocumentsLoader
import uuid
from utils.validators import validate_files

FILES_ROUTER = APIRouter(prefix="/files", tags=["Files"])
logger = logging.getLogger(__name__)


def _build_fallback_document(file_path: str, reason: str) -> str:
    file_name = os.path.basename(file_path)
    return (
        f"# Imported document: {file_name}\n\n"
        "Automatic parsing failed, so the file was kept as source context.\n\n"
        f"Reason: {reason}\n\n"
        "You can continue slide generation, but quality may improve if this file is re-uploaded as plain text/PDF."
    )


@FILES_ROUTER.post("/upload", response_model=List[str])
async def upload_files(files: Optional[List[UploadFile]]):
    if not files:
        raise HTTPException(400, "Documents are required")

    temp_dir = TEMP_FILE_SERVICE.create_temp_dir(str(uuid.uuid4()))

    validate_files(files, True, True, 100, UPLOAD_ACCEPTED_FILE_TYPES)

    temp_files: List[str] = []
    if files:
        for each_file in files:
            temp_path = TEMP_FILE_SERVICE.create_temp_file_path(
                each_file.filename, temp_dir
            )
            with open(temp_path, "wb") as f:
                content = await each_file.read()
                f.write(content)

            temp_files.append(temp_path)

    return temp_files


@FILES_ROUTER.post("/decompose", response_model=List[DecomposedFileInfo])
async def decompose_files(file_paths: Annotated[List[str], Body(embed=True)]):
    if not file_paths:
        raise HTTPException(status_code=400, detail="file_paths is required")

    temp_dir = TEMP_FILE_SERVICE.create_temp_dir(str(uuid.uuid4()))

    try:
        txt_files = []
        other_files = []
        for file_path in file_paths:
            if str(file_path).lower().endswith(".txt"):
                txt_files.append(file_path)
            else:
                other_files.append(file_path)

        response = []
        for each_file in other_files:
            parsed_doc = ""
            try:
                documents_loader = DocumentsLoader(file_paths=[each_file])
                await documents_loader.load_documents(temp_dir)
                parsed_doc = (
                    documents_loader.documents[0]
                    if documents_loader.documents
                    else ""
                )
            except Exception as exc:
                logger.exception(
                    "Document decompose fallback engaged for file=%s",
                    each_file,
                )
                parsed_doc = _build_fallback_document(each_file, str(exc))

            parsed_doc = str(parsed_doc or "").replace("<br>", "\n").strip()
            if not parsed_doc:
                parsed_doc = _build_fallback_document(
                    each_file, "Parser returned empty content."
                )

            file_path = TEMP_FILE_SERVICE.create_temp_file_path(
                f"{uuid.uuid4()}.txt", temp_dir
            )
            with open(file_path, "w", encoding="utf-8") as text_file:
                text_file.write(parsed_doc)
            response.append(
                DecomposedFileInfo(
                    name=os.path.basename(each_file), file_path=file_path
                )
            )

        # Return the txt documents as it is
        for each_file in txt_files:
            response.append(
                DecomposedFileInfo(name=os.path.basename(each_file), file_path=each_file)
            )

        return response
    except Exception as exc:
        logger.exception("Decompose failed unexpectedly, applying full fallback")
        fallback_response: List[DecomposedFileInfo] = []
        for each_file in file_paths:
            file_name = os.path.basename(each_file)
            if str(each_file).lower().endswith(".txt"):
                fallback_response.append(
                    DecomposedFileInfo(name=file_name, file_path=each_file)
                )
                continue

            fallback_text = _build_fallback_document(each_file, str(exc))
            fallback_path = TEMP_FILE_SERVICE.create_temp_file_path(
                f"{uuid.uuid4()}.txt", temp_dir
            )
            with open(fallback_path, "w", encoding="utf-8") as text_file:
                text_file.write(fallback_text)
            fallback_response.append(
                DecomposedFileInfo(name=file_name, file_path=fallback_path)
            )
        return fallback_response


@FILES_ROUTER.post("/update")
async def update_files(
    file_path: Annotated[str, Body()],
    file: Annotated[UploadFile, File()],
):
    with open(file_path, "wb") as f:
        f.write(await file.read())

    return {"message": "File updated successfully"}
