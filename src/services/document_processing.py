"""Configurable document extraction shared by ingestion and preview.

Auto stays local. Cloud parsers run only when explicitly selected. Optional
packages/models are not downloaded by saving a setting or listing capabilities.
"""

import asyncio
import base64
import importlib.util
import os
import json
import signal
import sys
from pathlib import Path
import tempfile
from typing import Literal

import httpx
from pydantic import BaseModel, Field

_PARSER_WORKER = False


async def run_parser_process(path: Path, output: Path, cfg, operation="preview"):
    """Isolate model startup, imports and child processes from the API server.

    Some agent imports add src/ to sys.path. Multiprocessing inherits that path
    and imports src/logging instead of Python's logging module. A fresh module
    entrypoint with a clean PYTHONPATH avoids this and permits a hard timeout.
    """
    root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="edunote-parser-worker-") as directory:
        request = Path(directory) / "request.json"
        result = Path(directory) / "result.json"
        request.write_text(json.dumps({"path": str(path.resolve()), "output": str(output.resolve()),
                                       "config": cfg.model_dump(), "operation": operation}))
        request.chmod(0o600)
        env = {**os.environ, "PYTHONPATH": str(root)}
        with tempfile.TemporaryFile() as errors:
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "src.services.document_processing",
                str(request), str(result), cwd=str(root), env=env,
                stdout=asyncio.subprocess.DEVNULL, stderr=errors, start_new_session=True,
            )
            try:
                await asyncio.wait_for(process.wait(), timeout=cfg.timeout_seconds)
                if not result.exists():
                    raise ValueError("Parser process exited without a result. Check parser runtime dependencies.")
                value = json.loads(result.read_text())
                if process.returncode or "error" in value:
                    raise ValueError(value.get("error", "Parser process failed"))
                return value
            except asyncio.TimeoutError as error:
                raise ValueError(f"Document extraction timed out after {cfg.timeout_seconds} seconds") from error
            finally:
                if process.returncode is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await process.wait()

SETTINGS_PATH = (
    Path(
        os.getenv(
            "EDUNOTE_SETTINGS_DIR", str(Path(__file__).resolve().parents[2] / "data/user/settings")
        )
    )
    / "document_processing.json"
)

PRESETS = [
    {"id": "auto", "label": "Auto · local text, then OCR", "parser": "auto"},
    {"id": "mineru", "label": "MinerU · local layout, tables, math", "parser": "mineru"},
    {
        "id": "mineru_http",
        "label": "MinerU API · self-hosted",
        "parser": "mineru_http",
        "base_url": "http://host.docker.internal:8002",
    },
    {"id": "docling", "label": "Docling · local document conversion", "parser": "docling"},
    {"id": "pymupdf", "label": "PyMuPDF · fast digital PDFs (no OCR)", "parser": "pymupdf"},
    {"id": "llamaparse", "label": "LlamaParse · cloud (sends documents)", "parser": "llamaparse"},
    {
        "id": "deepseek_ocr",
        "label": "DeepSeek OCR · self-hosted vision endpoint",
        "parser": "vision",
        "model": "deepseek-ai/DeepSeek-OCR",
        "base_url": "http://host.docker.internal:8000/v1",
    },
    {
        "id": "deepseek_ocr2",
        "label": "DeepSeek OCR-2 · self-hosted vision endpoint",
        "parser": "vision",
        "model": "deepseek-ai/DeepSeek-OCR-2",
        "base_url": "http://host.docker.internal:8000/v1",
    },
    {
        "id": "qwen_2b",
        "label": "Qwen3-VL 2B · compact vision OCR",
        "parser": "vision",
        "model": "Qwen/Qwen3-VL-2B-Instruct",
        "base_url": "http://host.docker.internal:8000/v1",
    },
    {
        "id": "qwen_8b",
        "label": "Qwen3-VL 8B · larger vision OCR",
        "parser": "vision",
        "model": "Qwen/Qwen3-VL-8B-Instruct",
        "base_url": "http://host.docker.internal:8000/v1",
    },
]


class DocumentProcessingConfig(BaseModel):
    parser: Literal[
        "auto", "pymupdf", "mineru", "mineru_http", "docling", "llamaparse", "vision"
    ] = "auto"
    fallback: Literal["none", "pymupdf"] = "none"
    mineru_tier: Literal["flash", "basic", "standard", "advanced"] = "basic"
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    max_pages: int = Field(default=100, ge=1, le=2000)
    timeout_seconds: int = Field(default=300, ge=5, le=1800)


def get_document_config() -> DocumentProcessingConfig:
    if SETTINGS_PATH.exists():
        return DocumentProcessingConfig.model_validate_json(SETTINGS_PATH.read_text())
    return DocumentProcessingConfig(parser=os.getenv("DOCUMENT_PARSER", "auto"))


def save_document_config(config: DocumentProcessingConfig) -> dict:
    previous = get_document_config()
    if config.api_key == "***":
        config = config.model_copy(update={"api_key": previous.api_key})
    if config.parser in {"vision", "mineru_http"}:
        from urllib.parse import urlparse

        parsed = urlparse(config.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Enter a valid HTTP(S) parser endpoint")
    if config.parser == "vision" and not config.model.strip():
        raise ValueError("A served vision model name is required")
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=SETTINGS_PATH.parent, delete=False) as stream:
        stream.write(config.model_dump_json(indent=2))
        temporary = Path(stream.name)
    temporary.chmod(0o600)
    temporary.replace(SETTINGS_PATH)
    return public_document_config(config)


def public_document_config(config=None) -> dict:
    result = (config or get_document_config()).model_dump()
    result["api_key"] = "***" if result["api_key"] else ""
    return result


def capabilities() -> list[dict]:
    packages = {
        "mineru": "mineru",
        "mineru_http": "mineru",
        "docling": "docling",
        "pymupdf": "fitz",
    }
    result = []
    for item in PRESETS:
        entry = dict(item)
        package = packages.get(item["parser"])
        entry["installed"] = importlib.util.find_spec(package) is not None if package else None
        entry["requires_endpoint"] = item["parser"] in {"vision", "mineru_http"}
        result.append(entry)
    return result


async def _extract(parser: str, path: Path, output: Path, cfg: DocumentProcessingConfig):
    if path.suffix.lower() in {".txt", ".md", ".tex", ".csv"}:
        return [{"type": "text", "text": path.read_text(encoding="utf-8"), "page_idx": 0}], []
    # Reuse the page/image normalization already supported by VGU Course.
    if parser == "pymupdf":
        from src.services.rag.pipelines.vgu_course import fallback_parse_document

        if path.suffix.lower() == ".pdf":
            import fitz

            with fitz.open(path) as document:
                if any(not page.get_text().strip() and page.get_images() for page in document):
                    raise ValueError("Scanned pages detected; select an OCR-capable parser")
        return await asyncio.to_thread(
            lambda: asyncio.run(
                fallback_parse_document(str(path), str(output), extract_images=True)
            )
        )
    if parser == "llamaparse":
        from src.services.rag.pipelines.vgu_course import parse_with_llamaparse

        key = cfg.api_key or os.getenv("LLAMAPARSE_API_KEY", "")
        if not key:
            raise ValueError(
                "Configure a LlamaParse API key in Documents settings or LLAMAPARSE_API_KEY"
            )
        return await parse_with_llamaparse(str(path), str(output), api_key=key)
    if parser in {"mineru", "mineru_http"}:
        if not _PARSER_WORKER:
            value = await run_parser_process(path, output, cfg.model_copy(update={"parser": parser}), "extract")
            return value["blocks"], value["images"]
        from importlib.metadata import version

        if int(version("mineru").split(".")[0]) >= 4:
            # Prefer the shipped CPU/ONNX profile on legacy CUDA deployments;
            # an explicit operator configuration always wins.
            profile = Path(__file__).resolve().parents[2] / "config" / "mineru.yaml"
            if profile.is_file():
                os.environ.setdefault("MINERU_CONFIG", str(profile))
            from mineru.parser import MinerUApiParser, ParseResult, parse_async

            if parser == "mineru_http":
                client = MinerUApiParser(
                    api_url=cfg.base_url,
                    api_key=cfg.api_key,
                    tier=cfg.mineru_tier,
                    include_images=True,
                )
                result = await asyncio.to_thread(client.parse, str(path))
            else:
                result = await parse_async(str(path), tier=cfg.mineru_tier)
            blocks = []
            for index, page in enumerate(result.pages):
                single = ParseResult(result.middle_json.model_copy(update={"pages": [page]}))
                blocks.append(
                    {
                        "type": "text",
                        "text": single.markdown(),
                        "page_idx": page.page_idx if page.page_idx is not None else index,
                    }
                )
            return blocks, []
        if parser == "mineru_http":
            raise ValueError("MinerU V1 API needs the MinerU >=4 SDK in the backend")
        from src.services.rag.components.parsers.mineru import async_parse_pdf_with_mineru

        if path.suffix.lower() != ".pdf":
            raise ValueError(
                "The legacy MinerU adapter accepts PDF; use MinerU 4 or Docling for Office documents"
            )
        return await async_parse_pdf_with_mineru(
            str(path), str(output), parse_method="auto", formula_enable=True, table_enable=True
        )
    if parser == "docling":

        def convert():
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions

            options = PdfPipelineOptions()
            if path.suffix.lower() == ".pdf":
                import fitz
                with fitz.open(path) as pdf:
                    # Avoid loading/running OCR over an existing digital text layer.
                    options.do_ocr = not all(page.get_text().strip() for page in pdf)
            converter = DocumentConverter(format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=options)
            })
            document = converter.convert(str(path)).document
            return [
                {
                    "type": "text",
                    "text": document.export_to_markdown(page_no=number),
                    "page_idx": number - 1,
                }
                for number in document.pages
            ], []

        return await asyncio.to_thread(convert)
    if parser == "vision":
        import fitz

        blocks = []
        headers = {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}
        async with httpx.AsyncClient(timeout=cfg.timeout_seconds, trust_env=False) as client:
            with fitz.open(path) as document:
                for index, page in enumerate(document):
                    pixmap = await asyncio.to_thread(
                        page.get_pixmap, matrix=fitz.Matrix(1.5, 1.5), alpha=False
                    )
                    encoded = base64.b64encode(pixmap.tobytes("png")).decode()
                    prompt = (
                        "<image>\n<|grounding|>Convert the document to markdown."
                        if "deepseek" in cfg.model.lower()
                        else "Extract this document page faithfully as Markdown. Preserve tables, formulas and reading order. Do not invent or summarize content."
                    )
                    response = await client.post(
                        cfg.base_url.rstrip("/") + "/chat/completions",
                        headers=headers,
                        json={
                            "model": cfg.model,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": prompt},
                                        {
                                            "type": "image_url",
                                            "image_url": {
                                                "url": f"data:image/png;base64,{encoded}"
                                            },
                                        },
                                    ],
                                }
                            ],
                            "temperature": 0,
                            "max_tokens": 8192,
                        },
                    )
                    response.raise_for_status()
                    choice = response.json()["choices"][0]
                    if choice.get("finish_reason") == "length":
                        raise ValueError(
                            f"OCR output truncated on page {index + 1}; use a larger output limit/model"
                        )
                    blocks.append(
                        {"type": "text", "text": choice["message"]["content"], "page_idx": index}
                    )
        return blocks, []
    raise ValueError(f"Unsupported parser: {parser}")


async def parse_document(file_path, output_dir, config=None) -> dict:
    path, output = Path(file_path), Path(output_dir)
    cfg = config or get_document_config()
    output.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".pdf":
        import fitz

        with fitz.open(path) as document:
            if len(document) > cfg.max_pages:
                raise ValueError(f"Document exceeds the configured limit of {cfg.max_pages} pages")
    chain = [cfg.parser]
    if cfg.parser == "auto":
        chain = ["pymupdf", "mineru", "docling"]
    elif cfg.fallback != "none" and cfg.fallback != cfg.parser:
        chain.append(cfg.fallback)
    warnings = []
    for parser in chain:
        try:
            blocks, images = await asyncio.wait_for(
                _extract(parser, path, output, cfg), timeout=cfg.timeout_seconds
            )
            text = "\n\n".join(
                str(block.get("text") or block.get("table_body") or block.get("content") or "")
                for block in blocks
            )
            if not text.strip():
                raise ValueError(
                    "No readable text extracted; select an OCR pipeline for scanned pages"
                )
            return {
                "content_list": blocks,
                "images": images,
                "parser": parser,
                "warnings": warnings,
            }
        except Exception as error:
            detail = str(error) or f"Extraction timed out after {cfg.timeout_seconds} seconds"
            warnings.append(f"{parser}: {type(error).__name__}: {detail}")
    raise ValueError("Document extraction failed. " + "; ".join(warnings))


async def preview_document(path, output, cfg):
    result = await parse_document(path, output, config=cfg)
    text = "\n\n".join(str(block.get("text", "")) for block in result["content_list"])
    return {"parser": result["parser"], "blocks": len(result["content_list"]),
            "preview": text[:4000], "warnings": result["warnings"]}


if __name__ == "__main__":
    _PARSER_WORKER = True
    request = json.loads(Path(sys.argv[1]).read_text())
    destination = Path(sys.argv[2])
    cfg = DocumentProcessingConfig.model_validate(request["config"])
    try:
        if request["operation"] == "extract":
            blocks, images = asyncio.run(_extract(cfg.parser, Path(request["path"]), Path(request["output"]), cfg))
            value = {"blocks": blocks, "images": images}
        else:
            value = asyncio.run(preview_document(Path(request["path"]), Path(request["output"]), cfg))
    except Exception as error:
        message = f"{type(error).__name__}: {error}"
        if cfg.api_key:
            message = message.replace(cfg.api_key, "[redacted]")
        destination.write_text(json.dumps({"error": message[:2000]}))
        destination.chmod(0o600)
        sys.exit(1)
    destination.write_text(json.dumps(value, default=str))
    destination.chmod(0o600)
