import mimetypes
from utils.safe_paths import workspace_file
from fastapi import HTTPException
import os, asyncio
from typing import List, Optional, Tuple
import pdfplumber
from pptx import Presentation

from constants.documents import (
    PDF_MIME_TYPES,
    POWERPOINT_TYPES,
    TEXT_MIME_TYPES,
    WORD_TYPES,
)
from services.docling_service import DoclingService


class DocumentsLoader:

    def __init__(self, file_paths: List[str]):
        self._file_paths = [workspace_file(path) for path in file_paths]

        self.docling_service = DoclingService()

        self._documents: List[str] = []
        self._images: List[List[str]] = []

    @property
    def documents(self):
        return self._documents

    @property
    def images(self):
        return self._images

    async def load_documents(
        self,
        temp_dir: Optional[str] = None,
        load_text: bool = True,
        load_images: bool = False,
    ):
        """If load_images is True, temp_dir must be provided"""

        documents: List[str] = []
        images: List[str] = []

        for file_path in self._file_paths:
            if not os.path.exists(file_path):
                raise HTTPException(
                    status_code=404, detail=f"File {file_path} not found"
                )

            document = ""
            imgs = []

            mime_type = mimetypes.guess_type(file_path)[0]
            if mime_type in PDF_MIME_TYPES:
                document, imgs = await self.load_pdf(
                    file_path, load_text, load_images, temp_dir
                )
            elif mime_type in TEXT_MIME_TYPES:
                document = await self.load_text(file_path)
            elif mime_type in POWERPOINT_TYPES:
                document = self.load_powerpoint(file_path)
            elif mime_type in WORD_TYPES:
                document = self.load_msword(file_path)

            documents.append(document)
            images.append(imgs)

        self._documents = documents
        self._images = images

    async def load_pdf(
        self,
        file_path: str,
        load_text: bool,
        load_images: bool,
        temp_dir: Optional[str] = None,
    ) -> Tuple[str, List[str]]:
        image_paths = []
        document: str = ""

        if load_text:
            # Docling can be expensive and unstable on some user-provided PDFs.
            # Prefer a lightweight text extraction path first so the request
            # does not fail for common text-based PDFs.
            document = await asyncio.to_thread(self.extract_pdf_text, file_path)

        if load_images:
            image_paths = await self.get_page_images_from_pdf_async(file_path, temp_dir)

        return document, image_paths

    async def load_text(self, file_path: str) -> str:
        file_path = workspace_file(file_path)
        with open(file_path, "r") as file:
            return await asyncio.to_thread(file.read)

    def load_msword(self, file_path: str) -> str:
        return self.docling_service.parse_to_markdown(file_path)

    def load_powerpoint(self, file_path: str) -> str:
        extracted = self.extract_powerpoint_text(file_path)
        return extracted or self.docling_service.parse_to_markdown(file_path)

    @classmethod
    def extract_pdf_text(cls, file_path: str) -> str:
        sections: List[str] = []

        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    try:
                        text = (page.extract_text() or "").strip()
                    except Exception:
                        text = ""

                    if text:
                        sections.append(f"## Page {page.page_number}\n{text}")
        except Exception:
            return ""

        return "\n\n".join(sections).strip()

    @classmethod
    def extract_powerpoint_text(cls, file_path: str) -> str:
        sections: List[str] = []

        try:
            presentation = Presentation(file_path)
        except Exception:
            return ""

        for index, slide in enumerate(presentation.slides, start=1):
            chunks: List[str] = []
            for shape in slide.shapes:
                text = getattr(shape, "text", "") or ""
                text = str(text).strip()
                if text:
                    chunks.append(text)

            if chunks:
                sections.append(f"## Slide {index}\n" + "\n".join(chunks))

        return "\n\n".join(sections).strip()

    @classmethod
    def get_page_images_from_pdf(cls, file_path: str, temp_dir: str) -> List[str]:
        with pdfplumber.open(file_path) as pdf:
            images = []
            for page in pdf.pages:
                img = page.to_image(resolution=150)
                image_path = os.path.join(temp_dir, f"page_{page.page_number}.png")
                img.save(image_path)
                images.append(image_path)
            return images

    @classmethod
    async def get_page_images_from_pdf_async(cls, file_path: str, temp_dir: str):
        return await asyncio.to_thread(
            cls.get_page_images_from_pdf, file_path, temp_dir
        )
