# -*- coding: utf-8 -*-
"""
MinerU Structure Parser
========================

GPU-accelerated document parser using MinerU (PDF-Extract-Kit).
Provides high-quality structure parsing with layout detection,
formula recognition, table extraction, and OCR.

Features:
- Layout detection (YOLO-based)
- Math formula recognition (UniMERNet)
- Table structure recognition (SlaNet+)
- OCR (PaddleOCR PyTorch)
- Reading order detection (LayoutReader)
- Automatic text/scanned PDF detection

Usage in VGU Course pipeline as Fallback 1:
  LlamaParse (cloud) → MinerU (local GPU) → PyMuPDF (basic)
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.logging import get_logger

logger = get_logger("mineru_parser")


def check_mineru_available() -> bool:
    """
    Check if MinerU is installed and models are available.

    Returns:
        True if MinerU is ready for use
    """
    try:
        from mineru.cli.common import do_parse  # noqa: F401
        return True
    except ImportError:
        return False


def check_mineru_models_ready() -> bool:
    """
    Check if MinerU models have been downloaded.

    Returns:
        True if models are available
    """
    try:
        from mineru.utils.config_reader import read_config
        config = read_config()
        if config is None:
            return False

        models_dir = config.get("models-dir", {})
        pipeline_dir = models_dir.get("pipeline", "")
        if not pipeline_dir or not os.path.isdir(pipeline_dir):
            return False

        # Check for key model files
        required_dirs = ["Layout", "MFD", "MFR", "OCR"]
        models_path = Path(pipeline_dir) / "models"
        for d in required_dirs:
            if not (models_path / d).is_dir():
                logger.warning(f"MinerU model directory missing: {d}")
                return False

        return True
    except Exception as e:
        logger.warning(f"Failed to check MinerU models: {e}")
        return False


def get_device() -> str:
    """
    Get the best available device for MinerU.

    Returns:
        Device string: 'cuda', 'cuda:0', 'cuda:1', 'cpu', etc.
    """
    # Check environment override
    env_device = os.environ.get("MINERU_DEVICE_MODE")
    if env_device:
        return env_device

    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass

    return "cpu"


def parse_pdf_with_mineru(
    file_path: str,
    output_dir: str,
    parse_method: str = "auto",
    device: Optional[str] = None,
    formula_enable: bool = True,
    table_enable: bool = True,
    language: str = "en",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    """
    Parse a PDF file using MinerU's Python API with GPU acceleration.

    This function calls MinerU's `do_parse` directly, avoiding CLI overhead.
    It produces structured content_list with layout analysis, formula recognition,
    table extraction, and OCR.

    Args:
        file_path: Path to the PDF file
        output_dir: Directory to save images and intermediate files
        parse_method: Parsing method - "auto" (detect), "txt" (text-based),
                      "ocr" (force OCR). Default "auto" detects automatically.
        device: Device for model inference ("cuda", "cpu", etc.)
                Defaults to auto-detection.
        formula_enable: Enable formula recognition (UniMERNet)
        table_enable: Enable table structure recognition (SlaNet+)
        language: Document language (e.g., "en", "vi", "zh")

    Returns:
        Tuple of (content_list, images_list, markdown_text):
        - content_list: List of content blocks compatible with VGU pipeline format
        - images_list: List of extracted image info dicts
        - markdown_text: Full markdown text output

    Raises:
        ImportError: If MinerU is not installed
        RuntimeError: If MinerU parsing fails
        FileNotFoundError: If the PDF file doesn't exist
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"PDF file not found: {file_path}")

    if not file_path.suffix.lower() == ".pdf":
        raise ValueError(f"Not a PDF file: {file_path}")

    # Set device
    if device is None:
        device = get_device()

    # Set environment for MinerU
    os.environ["MINERU_DEVICE_MODE"] = device
    logger.info(f"[MinerU] Device: {device}")

    # Import MinerU
    try:
        from mineru.cli.common import do_parse
    except ImportError:
        raise ImportError(
            "MinerU is not installed. Install with: pip install mineru"
        )

    # Prepare output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Read PDF bytes
    pdf_bytes = file_path.read_bytes()
    pdf_name = file_path.stem

    logger.info(
        f"[MinerU] Parsing: {file_path.name} "
        f"(method={parse_method}, formula={formula_enable}, table={table_enable})"
    )

    # Use a temp directory for MinerU output, then extract what we need
    with tempfile.TemporaryDirectory(prefix="mineru_") as temp_dir:
        try:
            # Call MinerU Python API
            do_parse(
                output_dir=temp_dir,
                pdf_file_names=[pdf_name],
                pdf_bytes_list=[pdf_bytes],
                p_lang_list=[language],
                backend="pipeline",
                parse_method=parse_method,
                formula_enable=formula_enable,
                table_enable=table_enable,
                # Disable unnecessary outputs to save disk/time
                f_draw_layout_bbox=False,
                f_draw_span_bbox=False,
                f_dump_model_output=False,
                f_dump_orig_pdf=False,
                # Keep essential outputs
                f_dump_md=True,
                f_dump_middle_json=False,
                f_dump_content_list=True,
                f_make_md_mode="mm_markdown",
            )
        except Exception as e:
            raise RuntimeError(f"MinerU parsing failed: {e}") from e

        # Find the output subdirectory
        # MinerU outputs to: {temp_dir}/{pdf_name}/{parse_method}/
        mineru_out = Path(temp_dir) / pdf_name / parse_method
        if not mineru_out.exists():
            # Try "auto" directory
            mineru_out = Path(temp_dir) / pdf_name / "auto"
        if not mineru_out.exists():
            # Try any subdirectory
            candidates = list(Path(temp_dir).rglob("*_content_list.json"))
            if candidates:
                mineru_out = candidates[0].parent
            else:
                raise RuntimeError(
                    f"MinerU output not found in {temp_dir}. "
                    f"Contents: {list(Path(temp_dir).rglob('*'))}"
                )

        # Read content_list.json
        content_list_file = None
        for f in mineru_out.glob("*_content_list.json"):
            content_list_file = f
            break

        if not content_list_file or not content_list_file.exists():
            raise RuntimeError(f"MinerU content_list.json not found in {mineru_out}")

        with open(content_list_file, "r", encoding="utf-8") as f:
            raw_content_list = json.load(f)

        # Read markdown
        markdown_text = ""
        for f in mineru_out.glob("*.md"):
            markdown_text = f.read_text(encoding="utf-8")
            break

        # Copy images to output directory
        images_src = mineru_out / "images"
        images_dst = output_path / "images"
        images_dst.mkdir(parents=True, exist_ok=True)

        images_list = []
        if images_src.exists():
            for img_file in images_src.iterdir():
                if img_file.is_file():
                    dst_file = images_dst / img_file.name
                    shutil.copy2(str(img_file), str(dst_file))
                    images_list.append({
                        "path": str(dst_file),
                        "name": img_file.name,
                        "page_idx": -1,  # Will be updated from content_list
                        "caption": "",
                    })

        # Convert MinerU content_list to VGU pipeline format
        content_list = _convert_mineru_to_pipeline_format(
            raw_content_list, str(images_dst)
        )

        logger.info(
            f"[MinerU] ✓ Parsed: {len(content_list)} blocks, "
            f"{len(images_list)} images, "
            f"{len(markdown_text)} chars markdown"
        )

        return content_list, images_list, markdown_text


def _convert_mineru_to_pipeline_format(
    raw_content_list: List[Dict[str, Any]],
    images_dir: str,
) -> List[Dict[str, Any]]:
    """
    Convert MinerU's native content_list format to VGU pipeline format.

    MinerU format:
        {"type": "text", "text": "...", "text_level": 1, "bbox": [...], "page_idx": 0}
        {"type": "image", "img_path": "images/xxx.jpg", "image_caption": [...], ...}
        {"type": "table", "text": "<table>...</table>", "bbox": [...], ...}
        {"type": "equation", "text": "$$...$$", "bbox": [...], ...}
        {"type": "discarded", ...}

    VGU pipeline format:
        {"type": "title", "text": "...", "page_idx": 0, "bbox": [...]}
        {"type": "text", "text": "...", "page_idx": 0, "bbox": [...]}
        {"type": "image", "img_path": "...", "img_caption": [...], "page_idx": 0}
        {"type": "table", "text": "...", "page_idx": 0, "bbox": [...]}

    Args:
        raw_content_list: MinerU's native content list
        images_dir: Directory containing extracted images

    Returns:
        Content list in VGU pipeline format
    """
    converted = []

    for item in raw_content_list:
        item_type = item.get("type", "")

        # Skip discarded items (page numbers, headers/footers detected by MinerU)
        if item_type == "discarded":
            continue

        if item_type == "text":
            text = item.get("text", "").strip()
            if not text:
                continue

            text_level = item.get("text_level", 0)

            # text_level > 0 means heading/title in MinerU
            if text_level and text_level > 0:
                content_type = "title"
            else:
                content_type = "text"

            converted.append({
                "type": content_type,
                "text": text,
                "page_idx": item.get("page_idx", 0),
                "bbox": item.get("bbox", [0, 0, 0, 0]),
            })

        elif item_type == "image":
            img_path = item.get("img_path", "")

            # Resolve image path relative to images_dir
            if img_path and not os.path.isabs(img_path):
                # MinerU uses relative paths like "images/xxx.jpg"
                img_filename = os.path.basename(img_path)
                full_img_path = os.path.join(images_dir, img_filename)
            else:
                full_img_path = img_path

            captions = item.get("image_caption", [])
            if isinstance(captions, str):
                captions = [captions] if captions else []

            converted.append({
                "type": "image",
                "img_path": full_img_path,
                "img_caption": captions,
                "page_idx": item.get("page_idx", 0),
                "bbox": item.get("bbox", [0, 0, 0, 0]),
            })

        elif item_type == "table":
            text = item.get("text", "").strip()
            if not text:
                continue

            converted.append({
                "type": "table",
                "text": text,
                "page_idx": item.get("page_idx", 0),
                "bbox": item.get("bbox", [0, 0, 0, 0]),
            })

        elif item_type == "equation":
            text = item.get("text", "").strip()
            if not text:
                continue

            # Equations are treated as text with LaTeX markup
            converted.append({
                "type": "equation",
                "text": text,
                "page_idx": item.get("page_idx", 0),
                "bbox": item.get("bbox", [0, 0, 0, 0]),
            })

    return converted


async def async_parse_pdf_with_mineru(
    file_path: str,
    output_dir: str,
    parse_method: str = "auto",
    device: Optional[str] = None,
    formula_enable: bool = True,
    table_enable: bool = True,
    language: str = "en",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Async wrapper for MinerU PDF parsing.

    MinerU itself is synchronous (GPU inference), so this runs it in
    a thread executor to avoid blocking the event loop.

    Args:
        Same as parse_pdf_with_mineru()

    Returns:
        Tuple of (content_list, images_list) - compatible with VGU pipeline
    """
    import asyncio

    loop = asyncio.get_event_loop()

    content_list, images_list, _markdown = await loop.run_in_executor(
        None,  # default executor (ThreadPoolExecutor)
        lambda: parse_pdf_with_mineru(
            file_path=file_path,
            output_dir=output_dir,
            parse_method=parse_method,
            device=device,
            formula_enable=formula_enable,
            table_enable=table_enable,
            language=language,
        )
    )

    return content_list, images_list
