#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MinerU integration tests.

These tests are intentionally guarded:
- Marked as integration
- Skipped when MinerU/models/test PDF are unavailable
"""

from pathlib import Path
import asyncio
import tempfile

import pytest

from src.services.rag.components.parsers.mineru import (
    async_parse_pdf_with_mineru,
    check_mineru_available,
    check_mineru_models_ready,
    get_device,
    parse_pdf_with_mineru,
)

pytestmark = pytest.mark.integration


def _resolve_test_pdf() -> Path | None:
    candidates = [
        Path("/app/data/knowledge_bases/Test/raw/ExploringCS. Lecture 10 - Recent Trends in Computer Science.pdf"),
        Path("/app/data/knowledge_bases/Test/raw/ExploringCS. Lecture 9 - Digital transformation.pdf"),
        Path("data/knowledge_bases/Test/raw/ExploringCS. Lecture 10 - Recent Trends in Computer Science.pdf"),
        Path("data/knowledge_bases/Test/raw/ExploringCS. Lecture 9 - Digital transformation.pdf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _skip_if_mineru_unavailable():
    if not check_mineru_available():
        pytest.skip("MinerU package is not installed")
    if not check_mineru_models_ready():
        pytest.skip("MinerU models are not ready")


def test_mineru_readiness():
    assert isinstance(check_mineru_available(), bool)
    assert isinstance(check_mineru_models_ready(), bool)
    assert isinstance(get_device(), str)


def test_parse_pdf_with_mineru_format():
    _skip_if_mineru_unavailable()
    test_pdf = _resolve_test_pdf()
    if test_pdf is None:
        pytest.skip("No integration PDF fixture found for MinerU test")

    with tempfile.TemporaryDirectory(prefix="mineru_integration_") as output_dir:
        content_list, images_list, markdown = parse_pdf_with_mineru(
            file_path=str(test_pdf),
            output_dir=output_dir,
            parse_method="auto",
            device="cuda",
            formula_enable=True,
            table_enable=True,
        )

    assert isinstance(content_list, list)
    assert isinstance(images_list, list)
    assert isinstance(markdown, str)
    assert len(content_list) > 0

    valid_types = {"title", "text", "image", "table", "equation"}
    for item in content_list:
        assert "type" in item
        assert "page_idx" in item
        assert item["type"] in valid_types
        if item["type"] == "image":
            assert "img_path" in item
        else:
            assert "text" in item


def test_async_parse_pdf_with_mineru_format():
    _skip_if_mineru_unavailable()
    test_pdf = _resolve_test_pdf()
    if test_pdf is None:
        pytest.skip("No integration PDF fixture found for MinerU async test")

    with tempfile.TemporaryDirectory(prefix="mineru_async_") as output_dir:
        content_list, images_list = asyncio.run(
            async_parse_pdf_with_mineru(
                file_path=str(test_pdf),
                output_dir=output_dir,
                parse_method="auto",
            )
        )

    assert isinstance(content_list, list)
    assert isinstance(images_list, list)
    assert len(content_list) > 0


def test_parse_pdf_with_mineru_error_handling(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        parse_pdf_with_mineru(str(tmp_path / "missing.pdf"), str(tmp_path))

    not_pdf = tmp_path / "sample.txt"
    not_pdf.write_text("not pdf", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_pdf_with_mineru(str(not_pdf), str(tmp_path))
