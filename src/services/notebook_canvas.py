# -*- coding: utf-8 -*-
"""
Advanced Notebook Canvas service.

Stores canvas draft sessions and runs OCR/structure/linking/quality pipeline.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import secrets
import time
from typing import Any

import httpx

from src.api.utils.notebook_manager import notebook_manager
from src.logging import get_logger
from src.services.llm import complete
from src.utils.json_parser import parse_json_response


logger = get_logger("NotebookCanvas")


def _now_ts() -> float:
    return time.time()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _extract_data_url_content(data_url: str) -> bytes:
    if not isinstance(data_url, str):
        raise ValueError("snapshot_data_url must be string")
    if "," not in data_url:
        raise ValueError("Invalid data URL")
    _prefix, encoded = data_url.split(",", 1)
    return base64.b64decode(encoded)


def _bbox_from_vertices(vertices: list[dict[str, Any]]) -> dict[str, float]:
    xs = [_safe_float(v.get("x", 0.0)) for v in vertices]
    ys = [_safe_float(v.get("y", 0.0)) for v in vertices]
    if not xs or not ys:
        return {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}
    x_min = min(xs)
    y_min = min(ys)
    x_max = max(xs)
    y_max = max(ys)
    return {
        "x": x_min,
        "y": y_min,
        "w": max(0.0, x_max - x_min),
        "h": max(0.0, y_max - y_min),
    }


def _bbox_intersects(a: dict[str, float], b: dict[str, float]) -> bool:
    ax2 = a["x"] + a["w"]
    ay2 = a["y"] + a["h"]
    bx2 = b["x"] + b["w"]
    by2 = b["y"] + b["h"]
    return not (ax2 < b["x"] or bx2 < a["x"] or ay2 < b["y"] or by2 < a["y"])


def _bbox_union(boxes: list[dict[str, float]]) -> dict[str, float]:
    if not boxes:
        return {"x": 0.0, "y": 0.0, "w": 0.0, "h": 0.0}
    x_min = min(box["x"] for box in boxes)
    y_min = min(box["y"] for box in boxes)
    x_max = max(box["x"] + box["w"] for box in boxes)
    y_max = max(box["y"] + box["h"] for box in boxes)
    return {"x": x_min, "y": y_min, "w": max(0.0, x_max - x_min), "h": max(0.0, y_max - y_min)}


def _word_text_from_symbols(symbols: list[dict[str, Any]]) -> str:
    if not isinstance(symbols, list):
        return ""
    return "".join(str(symbol.get("text", "")) for symbol in symbols).strip()


def _collect_word_blocks_from_fulltext(page_index: int, response_entry: dict[str, Any]) -> list[dict[str, Any]]:
    full_text = response_entry.get("fullTextAnnotation", {})
    pages = full_text.get("pages", []) if isinstance(full_text, dict) else []
    words: list[dict[str, Any]] = []
    counter = 0
    for page in pages:
        blocks = page.get("blocks", []) if isinstance(page, dict) else []
        for block in blocks:
            paragraphs = block.get("paragraphs", []) if isinstance(block, dict) else []
            for paragraph in paragraphs:
                for word in paragraph.get("words", []) if isinstance(paragraph, dict) else []:
                    text = _word_text_from_symbols(word.get("symbols", []))
                    if not text:
                        continue
                    counter += 1
                    bounding_box = word.get("boundingBox", {}) if isinstance(word, dict) else {}
                    vertices = bounding_box.get("vertices", []) if isinstance(bounding_box, dict) else []
                    if (not vertices) and isinstance(bounding_box, dict):
                        normalized_vertices = bounding_box.get("normalizedVertices", [])
                        if isinstance(normalized_vertices, list) and normalized_vertices:
                            page_width = max(1.0, _safe_float(page.get("width"), 1.0))
                            page_height = max(1.0, _safe_float(page.get("height"), 1.0))
                            vertices = [
                                {
                                    "x": _safe_float(vertex.get("x"), 0.0) * page_width,
                                    "y": _safe_float(vertex.get("y"), 0.0) * page_height,
                                }
                                for vertex in normalized_vertices
                                if isinstance(vertex, dict)
                            ]
                    bbox = _bbox_from_vertices(vertices)
                    words.append(
                        {
                            "id": f"p{page_index}_w{counter}",
                            "page_index": page_index,
                            "text": text,
                            "bbox": bbox,
                            "confidence": _safe_float(word.get("confidence"), 0.65),
                            "source": "google_vision_word",
                        }
                    )
    return words


def _merge_words_into_lines(word_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not word_blocks:
        return []

    by_page: dict[int, list[dict[str, Any]]] = {}
    for block in word_blocks:
        page_index = _safe_int(block.get("page_index"), 0)
        by_page.setdefault(page_index, []).append(block)

    merged: list[dict[str, Any]] = []
    for page_index, page_words in by_page.items():
        page_words = sorted(
            page_words,
            key=lambda block: (
                _safe_float((block.get("bbox") or {}).get("y"), 0.0),
                _safe_float((block.get("bbox") or {}).get("x"), 0.0),
            ),
        )
        heights = [
            max(1.0, _safe_float((block.get("bbox") or {}).get("h"), 0.0))
            for block in page_words
            if isinstance(block.get("bbox"), dict)
        ]
        median_height = sorted(heights)[len(heights) // 2] if heights else 24.0
        same_line_threshold = max(12.0, median_height * 0.9)

        lines: list[dict[str, Any]] = []
        for block in page_words:
            bbox = block.get("bbox", {})
            center_y = _safe_float(bbox.get("y"), 0.0) + _safe_float(bbox.get("h"), 0.0) / 2.0
            best_idx = -1
            best_delta = float("inf")
            for idx, line in enumerate(lines):
                delta = abs(center_y - line["center_y"])
                if delta <= same_line_threshold and delta < best_delta:
                    best_delta = delta
                    best_idx = idx
            if best_idx >= 0:
                target = lines[best_idx]
                target["words"].append(block)
                target["center_y"] = (target["center_y"] * (len(target["words"]) - 1) + center_y) / len(
                    target["words"]
                )
            else:
                lines.append({"center_y": center_y, "words": [block]})

        lines.sort(key=lambda line: _safe_float(line.get("center_y"), 0.0))
        line_counter = 0
        for line in lines:
            words = sorted(
                line["words"],
                key=lambda block: _safe_float((block.get("bbox") or {}).get("x"), 0.0),
            )
            segments: list[list[dict[str, Any]]] = []
            current_segment: list[dict[str, Any]] = []
            segment_gap_threshold = max(26.0, median_height * 1.8)
            for word in words:
                if not current_segment:
                    current_segment = [word]
                    continue
                previous = current_segment[-1]
                prev_box = previous.get("bbox", {})
                curr_box = word.get("bbox", {})
                prev_right = _safe_float(prev_box.get("x"), 0.0) + _safe_float(prev_box.get("w"), 0.0)
                gap = _safe_float(curr_box.get("x"), 0.0) - prev_right
                if gap > segment_gap_threshold:
                    segments.append(current_segment)
                    current_segment = [word]
                else:
                    current_segment.append(word)
            if current_segment:
                segments.append(current_segment)

            for segment in segments:
                tokens = [str(word.get("text", "")).strip() for word in segment]
                merged_text = " ".join(token for token in tokens if token).strip()
                if not merged_text:
                    continue

                line_counter += 1
                component_boxes = [
                    block.get("bbox", {})
                    for block in segment
                    if isinstance(block.get("bbox"), dict)
                ]
                component_confidences = sorted(
                    _safe_float(block.get("confidence"), 0.0) for block in segment
                )
                if component_confidences:
                    q1_idx = max(0, min(len(component_confidences) - 1, int(len(component_confidences) * 0.25)))
                    line_conf = component_confidences[q1_idx]
                else:
                    line_conf = 0.0

                merged.append(
                    {
                        "id": f"p{page_index}_l{line_counter}",
                        "page_index": page_index,
                        "text": merged_text,
                        "bbox": _bbox_union(component_boxes),
                        "confidence": round(line_conf, 4),
                        "source": "google_vision_line_merge",
                        "component_ids": [str(block.get("id", "")) for block in segment],
                    }
                )
    return merged


def _is_equation_text(text: str) -> bool:
    if not text:
        return False
    patterns = [
        r"\\(frac|sum|int|sqrt|alpha|beta|gamma|theta|pi|lambda)",
        r"[0-9]+\s*[\+\-\*/=]\s*[0-9a-zA-Z]",
        r"[a-zA-Z]\^[0-9a-zA-Z]",
        r"\b(sin|cos|tan|log|ln)\b",
        r"[∑∫√≈≠≤≥±]",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _normalize_equation_text(text: str) -> str:
    normalized = " ".join(str(text).strip().split())
    if not normalized:
        return normalized
    if normalized.startswith("$$") and normalized.endswith("$$"):
        return normalized
    return f"$$ {normalized} $$"


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


@dataclass
class CanvasPaths:
    base_dir: Path

    @property
    def data_root(self) -> Path:
        return self.base_dir

    def session_dir(self, session_id: str) -> Path:
        return self.base_dir / session_id

    def session_file(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "session.json"

    def page_snapshot_file(self, session_id: str, page_index: int) -> Path:
        return self.session_dir(session_id) / f"page_{page_index}.png"


class NotebookCanvasService:
    def __init__(self, base_dir: Path | None = None):
        if base_dir is None:
            project_root = Path(__file__).resolve().parents[2]
            base_dir = project_root / "data" / "user" / "notebook" / "canvas"
        self.paths = CanvasPaths(base_dir=base_dir)
        self.paths.data_root.mkdir(parents=True, exist_ok=True)

    def _create_session_id(self) -> str:
        return f"cnv_{int(time.time())}_{secrets.token_hex(3)}"

    def _load_session(self, session_id: str) -> dict[str, Any] | None:
        session_file = self.paths.session_file(session_id)
        if not session_file.exists():
            return None
        try:
            with open(session_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning(f"Failed to read canvas session {session_id}: {exc}")
            return None

    def _save_session(self, session: dict[str, Any]) -> None:
        session_id = str(session["session_id"])
        session_dir = self.paths.session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        session["updated_at"] = _now_ts()
        with open(self.paths.session_file(session_id), "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)

    def create_session(self, title: str = "", notebook_id: str | None = None) -> dict[str, Any]:
        session_id = self._create_session_id()
        now = _now_ts()
        session = {
            "session_id": session_id,
            "title": title.strip() or "Advanced Notebook Canvas",
            "notebook_id": notebook_id,
            "status": "draft",
            "created_at": now,
            "updated_at": now,
            "pages": [],
            "layers": [{"id": "layer_main", "name": "Main", "visible": True, "locked": False}],
            "strokes_total": 0,
            "ocr_blocks": [],
            "ocr_diagnostics": [],
            "structured": {"blocks": [], "markdown": ""},
            "review_issues": [],
            "quality": {"ocr_confidence": 0.0, "needs_review": False},
            "metadata": {
                "source": "advanced_canvas",
                "structure_version": "v1",
                "overlay_version": "v1",
            },
            "confirmed_at": None,
            "committed_at": None,
            "committed_record_id": None,
        }
        self._save_session(session)
        return session

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self._load_session(session_id)

    def _collect_overlay_blocks(
        self, page_index: int, overlays: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]]:
        if not overlays:
            return []

        blocks: list[dict[str, Any]] = []
        for index, overlay in enumerate(overlays, start=1):
            if not isinstance(overlay, dict):
                continue
            overlay_type = _safe_str(overlay.get("type")).lower() or "text"
            text = _safe_str(overlay.get("text"))
            if not text:
                continue

            x = max(0.0, _safe_float(overlay.get("x"), 0.0))
            y = max(0.0, _safe_float(overlay.get("y"), 0.0))
            w = max(1.0, _safe_float(overlay.get("w"), 120.0))
            h = max(1.0, _safe_float(overlay.get("h"), 40.0))
            block_id = _safe_str(overlay.get("id")) or f"p{page_index}_ov{index}"

            font_size = _safe_float((overlay.get("style") or {}).get("fontSize"), 0.0)
            is_heading = overlay_type == "text" and font_size >= 28.0
            block_type = "equation" if overlay_type == "equation" else ("heading" if is_heading else "paragraph")
            normalized_text = _normalize_equation_text(text) if block_type == "equation" else text

            blocks.append(
                {
                    "id": block_id,
                    "page_index": page_index,
                    "text": text,
                    "bbox": {"x": x, "y": y, "w": w, "h": h},
                    "confidence": 0.99,
                    "source": f"canvas_overlay_{overlay_type}",
                    "block_type": block_type,
                    "normalized_text": normalized_text,
                    "overlay": True,
                }
            )
        return blocks

    def add_strokes_batch(
        self,
        session_id: str,
        *,
        page_index: int,
        strokes: list[dict[str, Any]],
        overlays: list[dict[str, Any]] | None = None,
        layers: list[dict[str, Any]] | None = None,
        dirty_regions: list[dict[str, Any]] | None = None,
        snapshot_data_url: str | None = None,
        replace_page: bool = False,
    ) -> dict[str, Any]:
        session = self._load_session(session_id)
        if not session:
            raise FileNotFoundError(f"Canvas session not found: {session_id}")

        page_index = max(0, _safe_int(page_index))
        pages: list[dict[str, Any]] = session.get("pages", [])

        existing_page = None
        for page in pages:
            if _safe_int(page.get("page_index"), -1) == page_index:
                existing_page = page
                break
        if existing_page is None:
            existing_page = {
                "page_index": page_index,
                "strokes": [],
                "overlays": [],
                "dirty_regions": [],
                "snapshot_url": "",
                "updated_at": _now_ts(),
            }
            pages.append(existing_page)

        if replace_page:
            existing_page["strokes"] = strokes[:]
        else:
            existing_page["strokes"].extend(strokes)
        if overlays is not None:
            existing_page["overlays"] = overlays[:]

        if dirty_regions:
            existing_page["dirty_regions"] = dirty_regions
        existing_page["updated_at"] = _now_ts()

        if layers is not None:
            session["layers"] = layers

        if snapshot_data_url:
            snapshot_bytes = _extract_data_url_content(snapshot_data_url)
            snapshot_path = self.paths.page_snapshot_file(session_id, page_index)
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            with open(snapshot_path, "wb") as f:
                f.write(snapshot_bytes)
            existing_page["snapshot_url"] = (
                f"/api/outputs/notebook/canvas/{session_id}/page_{page_index}.png"
            )

        session["pages"] = sorted(pages, key=lambda page: _safe_int(page.get("page_index"), 0))
        session["strokes_total"] = sum(
            len(page.get("strokes", [])) for page in session.get("pages", [])
        )
        self._save_session(session)
        return session

    async def _ocr_page(
        self, session_id: str, page_index: int, dirty_regions: list[dict[str, Any]] | None = None
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        snapshot_path = self.paths.page_snapshot_file(session_id, page_index)
        if not snapshot_path.exists():
            return [], {
                "page_index": page_index,
                "provider": "google_vision",
                "api_key_configured": bool((os.getenv("GOOGLE_API_KEY") or "").strip()),
                "success": False,
                "status_code": None,
                "used_fallback": True,
                "message": "Snapshot image not found for this page.",
            }

        with open(snapshot_path, "rb") as f:
            image_bytes = f.read()
        encoded = base64.b64encode(image_bytes).decode("ascii")

        api_key = (os.getenv("GOOGLE_API_KEY") or "").strip()
        endpoint = (
            os.getenv("GOOGLE_VISION_ENDPOINT")
            or "https://vision.googleapis.com/v1/images:annotate"
        ).strip()

        blocks: list[dict[str, Any]] = []
        diagnostics: dict[str, Any] = {
            "page_index": page_index,
            "provider": "google_vision",
            "api_key_configured": bool(api_key),
            "success": False,
            "status_code": None,
            "used_fallback": False,
            "message": "",
        }
        fallback_reason = ""
        if api_key:
            payload = {
                "requests": [
                    {
                        "image": {"content": encoded},
                        "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                    }
                ]
            }
            try:
                async with httpx.AsyncClient(timeout=35.0) as client:
                    response = await client.post(
                        endpoint,
                        params={"key": api_key},
                        json=payload,
                    )
                diagnostics["status_code"] = response.status_code
                if response.status_code == 200:
                    data = response.json()
                    response_entry = (
                        data.get("responses", [{}])[0]
                        if isinstance(data.get("responses"), list)
                        else {}
                    )
                    if not isinstance(response_entry, dict):
                        response_entry = {}

                    response_error = response_entry.get("error", {})
                    if isinstance(response_error, dict) and response_error.get("message"):
                        fallback_reason = str(response_error.get("message", "")).strip()
                        diagnostics["message"] = fallback_reason
                        logger.warning(
                            "Google Vision OCR returned embedded error for canvas session=%s page=%s error=%s",
                            session_id,
                            page_index,
                            fallback_reason,
                        )
                    else:
                        word_blocks = _collect_word_blocks_from_fulltext(page_index, response_entry)
                        merged_lines = _merge_words_into_lines(word_blocks)
                        if merged_lines:
                            blocks = merged_lines[:120]
                            diagnostics["success"] = True
                            diagnostics["word_count"] = len(word_blocks)
                            diagnostics["line_count"] = len(merged_lines)
                            diagnostics["message"] = (
                                f"Vision OCR detected {len(word_blocks)} words, merged into {len(merged_lines)} lines."
                            )
                        else:
                            annotations = response_entry.get("textAnnotations", [])
                            if not isinstance(annotations, list):
                                annotations = []
                            for idx, ann in enumerate(annotations[1:121], start=1):
                                if not isinstance(ann, dict):
                                    continue
                                text = str(ann.get("description", "")).strip()
                                if not text:
                                    continue
                                vertices = ann.get("boundingPoly", {}).get("vertices", [])
                                bbox = _bbox_from_vertices(vertices)
                                blocks.append(
                                    {
                                        "id": f"p{page_index}_b{idx}",
                                        "page_index": page_index,
                                        "text": text,
                                        "bbox": bbox,
                                        "confidence": _safe_float(ann.get("confidence"), 0.62),
                                        "source": "google_vision_text_annotation",
                                    }
                                )
                            diagnostics["success"] = bool(blocks)
                            diagnostics["message"] = (
                                f"Vision OCR fallback parsed {len(blocks)} textAnnotations blocks."
                                if blocks
                                else "Vision OCR returned no detectable words."
                            )
                else:
                    fallback_reason = (
                        response.json().get("error", {}).get("message", "")  # type: ignore[union-attr]
                        if "application/json" in (response.headers.get("content-type") or "")
                        else ""
                    )
                    if not fallback_reason:
                        fallback_reason = f"Vision API returned HTTP {response.status_code}."
                    diagnostics["message"] = fallback_reason
                    logger.warning(
                        "Google Vision OCR non-200 for canvas session=%s page=%s status=%s reason=%s",
                        session_id,
                        page_index,
                        response.status_code,
                        fallback_reason,
                    )
            except Exception as exc:
                fallback_reason = str(exc)
                diagnostics["message"] = fallback_reason
                logger.warning(
                    f"Google Vision OCR failed for canvas session={session_id} page={page_index}: {exc}"
                )
        else:
            fallback_reason = "GOOGLE_API_KEY is not configured."
            diagnostics["message"] = fallback_reason

        if not blocks:
            # Deterministic fallback: keep session process runnable even when Vision is unavailable.
            diagnostics["used_fallback"] = True
            blocks.append(
                {
                    "id": f"p{page_index}_b1",
                    "page_index": page_index,
                    "text": (
                        f"Canvas page {page_index + 1} "
                        f"(OCR unavailable: {fallback_reason or 'unknown reason'}, please confirm manually)."
                    ),
                    "bbox": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
                    "confidence": 0.35,
                    "source": "fallback",
                }
            )

        if dirty_regions:
            normalized_regions: list[dict[str, float]] = []
            for region in dirty_regions:
                normalized_regions.append(
                    {
                        "x": _safe_float(region.get("x"), 0.0),
                        "y": _safe_float(region.get("y"), 0.0),
                        "w": max(0.0, _safe_float(region.get("w"), 0.0)),
                        "h": max(0.0, _safe_float(region.get("h"), 0.0)),
                    }
                )
            blocks = [
                block
                for block in blocks
                if any(_bbox_intersects(block["bbox"], region) for region in normalized_regions)
            ] or blocks

        return blocks, diagnostics

    async def _llm_structure_blocks(
        self, raw_blocks: list[dict[str, Any]]
    ) -> list[dict[str, Any]] | None:
        model = (os.getenv("CANVAS_STRUCTURE_MODEL") or "").strip() or None
        if not raw_blocks:
            return []

        block_payload = [
            {
                "id": block.get("id"),
                "page_index": block.get("page_index"),
                "text": str(block.get("text", ""))[:400],
                "confidence": block.get("confidence"),
            }
            for block in raw_blocks[:120]
        ]
        system_prompt = (
            "You classify OCR blocks from handwritten notebook canvas. "
            "Return JSON object: {\"blocks\":[{\"id\":\"...\",\"block_type\":\"heading|paragraph|equation|diagram|shape-note\",\"normalized_text\":\"...\"}]}"
        )
        prompt = (
            "Classify each block and normalize text. Keep equations compact in LaTeX when possible.\n"
            f"Blocks:\n{json.dumps(block_payload, ensure_ascii=False)}"
        )
        try:
            response = await complete(
                prompt=prompt,
                system_prompt=system_prompt,
                model=model,
                temperature=0.1,
                max_tokens=1400,
            )
            parsed = parse_json_response(response, fallback={})
            items = parsed.get("blocks") if isinstance(parsed, dict) else None
            if isinstance(items, list):
                result: list[dict[str, Any]] = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    result.append(
                        {
                            "id": str(item.get("id", "")).strip(),
                            "block_type": str(item.get("block_type", "paragraph")).strip(),
                            "normalized_text": str(item.get("normalized_text", "")).strip(),
                        }
                    )
                return result
        except Exception as exc:
            logger.warning(f"Canvas structure LLM fallback engaged: {exc}")
        return None

    async def _structure_blocks(self, raw_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        llm_map: dict[str, dict[str, Any]] = {}
        llm_classified = await self._llm_structure_blocks(raw_blocks)
        if llm_classified:
            llm_map = {str(item.get("id")): item for item in llm_classified if item.get("id")}

        structured: list[dict[str, Any]] = []
        for block in raw_blocks:
            block_id = str(block.get("id"))
            text = str(block.get("text", "")).strip()
            source = str(block.get("source", "")).strip()

            if source.startswith("canvas_overlay_") or bool(block.get("overlay")):
                block_type = str(block.get("block_type", "paragraph")).strip().lower()
                if block_type not in {"heading", "paragraph", "equation", "diagram", "shape-note"}:
                    block_type = "equation" if source.endswith("equation") else "paragraph"
                normalized_text = str(block.get("normalized_text", "")).strip() or text
                if block_type == "equation":
                    normalized_text = _normalize_equation_text(normalized_text)
                structured.append(
                    {
                        **block,
                        "block_type": block_type,
                        "normalized_text": normalized_text,
                    }
                )
                continue

            llm_item = llm_map.get(block_id, {})

            block_type = str(llm_item.get("block_type", "")).strip().lower()
            normalized_text = str(llm_item.get("normalized_text", "")).strip()

            if block_type not in {"heading", "paragraph", "equation", "diagram", "shape-note"}:
                if _is_equation_text(text):
                    block_type = "equation"
                elif len(text) <= 80 and text == text.title():
                    block_type = "heading"
                elif any(keyword in text.lower() for keyword in ("diagram", "figure", "chart")):
                    block_type = "diagram"
                else:
                    block_type = "paragraph"

            if not normalized_text:
                normalized_text = text
            if block_type == "equation":
                normalized_text = _normalize_equation_text(normalized_text)

            structured.append(
                {
                    **block,
                    "block_type": block_type,
                    "normalized_text": normalized_text,
                }
            )
        return structured

    def _build_markdown(self, blocks: list[dict[str, Any]]) -> str:
        if not blocks:
            return ""
        sorted_blocks = sorted(
            blocks,
            key=lambda item: (
                _safe_int(item.get("page_index"), 0),
                _safe_float((item.get("bbox") or {}).get("y"), 0.0),
                _safe_float((item.get("bbox") or {}).get("x"), 0.0),
            ),
        )
        multiple_pages = len({item.get("page_index") for item in sorted_blocks}) > 1
        lines: list[str] = []
        current_page: int | None = None
        for block in sorted_blocks:
            page_index = _safe_int(block.get("page_index"), 0)
            text = str(block.get("normalized_text", "")).strip()
            if not text:
                continue
            if multiple_pages and page_index != current_page:
                if lines:
                    lines.append("")
                lines.append(f"### Page {page_index + 1}")
                lines.append("")
                current_page = page_index

            block_type = str(block.get("block_type", "paragraph"))
            if block_type == "heading":
                lines.append(f"## {text}")
            elif block_type == "equation":
                lines.append(text)
            elif block_type == "diagram":
                lines.append(f"> [Diagram] {text}")
            elif block_type == "shape-note":
                lines.append(f"- [Shape] {text}")
            else:
                lines.append(text)
            lines.append("")
        return "\n".join(lines).strip()

    def _quality_and_issues(
        self, structured_blocks: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if not structured_blocks:
            return {"ocr_confidence": 0.0, "needs_review": False}, []

        confidences = [_safe_float(block.get("confidence"), 0.0) for block in structured_blocks]
        avg_conf = sum(confidences) / max(1, len(confidences))
        issues: list[dict[str, Any]] = []
        for block in structured_blocks:
            confidence = _safe_float(block.get("confidence"), 0.0)
            if confidence < 0.72:
                issues.append(
                    {
                        "block_id": block.get("id"),
                        "page_index": block.get("page_index"),
                        "reason": "Low OCR confidence",
                        "confidence": confidence,
                        "suggested_text": block.get("normalized_text", ""),
                    }
                )
        quality = {
            "ocr_confidence": round(avg_conf, 4),
            "needs_review": bool(issues),
            "block_count": len(structured_blocks),
        }
        return quality, issues

    async def process_session(self, session_id: str) -> dict[str, Any]:
        session = self._load_session(session_id)
        if not session:
            raise FileNotFoundError(f"Canvas session not found: {session_id}")

        raw_blocks: list[dict[str, Any]] = []
        overlay_blocks: list[dict[str, Any]] = []
        ocr_diagnostics: list[dict[str, Any]] = []
        for page in session.get("pages", []):
            page_index = _safe_int(page.get("page_index"), 0)
            # Always process full page for stable OCR quality and confidence.
            # Dirty-region filtering can drop valid words and degrade accuracy.
            page_blocks, page_diag = await self._ocr_page(
                session_id=session_id,
                page_index=page_index,
                dirty_regions=None,
            )
            raw_blocks.extend(page_blocks)
            overlay_blocks.extend(
                self._collect_overlay_blocks(page_index, page.get("overlays"))
            )
            ocr_diagnostics.append(page_diag)

        all_blocks = raw_blocks + overlay_blocks
        structured_blocks = await self._structure_blocks(all_blocks)
        markdown = self._build_markdown(structured_blocks)
        quality, issues = self._quality_and_issues(structured_blocks)

        session["ocr_blocks"] = all_blocks
        session["ocr_diagnostics"] = ocr_diagnostics
        session["structured"] = {"blocks": structured_blocks, "markdown": markdown}
        session["quality"] = quality
        session["review_issues"] = issues
        session["status"] = "processed"
        self._save_session(session)
        return session

    def confirm_blocks(self, session_id: str, updates: list[dict[str, Any]]) -> dict[str, Any]:
        session = self._load_session(session_id)
        if not session:
            raise FileNotFoundError(f"Canvas session not found: {session_id}")

        updates_by_id = {
            str(item.get("id")): item for item in updates if isinstance(item, dict) and item.get("id")
        }
        structured_blocks = session.get("structured", {}).get("blocks", [])
        if not isinstance(structured_blocks, list):
            structured_blocks = []

        for block in structured_blocks:
            block_id = str(block.get("id", ""))
            if block_id not in updates_by_id:
                continue
            patch = updates_by_id[block_id]
            if "text" in patch:
                block["normalized_text"] = str(patch.get("text", "")).strip()
            if "block_type" in patch:
                block_type = str(patch.get("block_type", "")).strip()
                if block_type in {"heading", "paragraph", "equation", "diagram", "shape-note"}:
                    block["block_type"] = block_type
            block["confidence"] = max(0.85, _safe_float(block.get("confidence"), 0.0))
            block["reviewed"] = True

        markdown = self._build_markdown(structured_blocks)
        quality, issues = self._quality_and_issues(structured_blocks)
        session["structured"] = {"blocks": structured_blocks, "markdown": markdown}
        session["quality"] = quality
        session["review_issues"] = issues
        session["confirmed_at"] = _now_ts()
        session["status"] = "confirmed" if not issues else "processed"
        self._save_session(session)
        return session

    def commit_session(
        self,
        session_id: str,
        *,
        notebook_id: str,
        title: str = "",
        user_query: str = "",
        force_commit: bool = False,
    ) -> dict[str, Any]:
        session = self._load_session(session_id)
        if not session:
            raise FileNotFoundError(f"Canvas session not found: {session_id}")
        review_issues = session.get("review_issues", [])
        if review_issues and not force_commit:
            raise ValueError("Session still has low-confidence OCR blocks, please confirm first.")

        markdown = (
            str(session.get("structured", {}).get("markdown", "")).strip()
            or "Canvas session has no recognized text yet."
        )
        page_count = len(session.get("pages", []))
        snapshot_urls = [
            page.get("snapshot_url", "")
            for page in session.get("pages", [])
            if isinstance(page.get("snapshot_url"), str) and page.get("snapshot_url")
        ]
        quality = session.get("quality", {}) if isinstance(session.get("quality"), dict) else {}
        structured_blocks = (
            session.get("structured", {}).get("blocks", [])
            if isinstance(session.get("structured", {}), dict)
            else []
        )
        overlay_blocks = [
            block
            for block in structured_blocks
            if isinstance(block, dict)
            and str(block.get("source", "")).startswith("canvas_overlay_")
        ]

        metadata = {
            "source": "advanced_canvas",
            "canvas_session_id": session_id,
            "page_count": page_count,
            "snapshot_urls": snapshot_urls,
            "ocr_confidence": _safe_float(quality.get("ocr_confidence"), 0.0),
            "needs_review": bool(quality.get("needs_review", False)),
            "structure_version": "v1",
            "blocks": structured_blocks,
            "overlay_blocks": overlay_blocks,
        }

        record_title = title.strip() or str(session.get("title") or "Advanced Notebook Canvas")
        record_query = user_query.strip() or f"Advanced canvas session {session_id}"
        result = notebook_manager.add_record(
            notebook_ids=[notebook_id],
            record_type="canvas",
            title=record_title,
            user_query=record_query,
            output=markdown,
            metadata=metadata,
            kb_name=None,
        )
        if notebook_id not in result.get("added_to_notebooks", []):
            raise FileNotFoundError(f"Notebook not found: {notebook_id}")

        session["status"] = "committed"
        session["committed_at"] = _now_ts()
        session["committed_record_id"] = result.get("record", {}).get("id")
        session["notebook_id"] = notebook_id
        self._save_session(session)
        return {"session": session, "record": result.get("record")}


notebook_canvas_service = NotebookCanvasService()
