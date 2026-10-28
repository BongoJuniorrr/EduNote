# -*- coding: utf-8 -*-
"""Slide Generator Pro orchestration engine (multi-agent pipeline)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import time
from collections import Counter
from typing import Any

from src.logging import get_logger
from src.services.llm import complete
from src.utils.json_parser import parse_json_response


logger = get_logger("SlideProEngine")

CANVAS_WIDTH = 1600
CANVAS_HEIGHT = 900


STYLE_PRESETS: list[dict[str, Any]] = [
    {
        "id": "academic_evidence",
        "name": "Academic Evidence",
        "description": "Evidence-first academic narrative with explicit source clarity.",
        "theme": {
            "palette": {
                "background": "#F6F9FF",
                "foreground": "#0F172A",
                "accent": "#0EA5E9",
                "muted": "#475569",
            },
            "fonts": {"title": "Sora", "body": "IBM Plex Sans"},
        },
    },
    {
        "id": "executive_data_story",
        "name": "Executive Data Story",
        "description": "Boardroom-grade data storytelling with concise recommendations.",
        "theme": {
            "palette": {
                "background": "#101826",
                "foreground": "#E5EDF8",
                "accent": "#38BDF8",
                "muted": "#A7B6CC",
            },
            "fonts": {"title": "Fraunces", "body": "Manrope"},
        },
    },
    {
        "id": "professional_showcase",
        "name": "Professional Showcase",
        "description": "Hero-style showcase with strong visual narrative and metrics.",
        "theme": {
            "palette": {
                "background": "#0B1020",
                "foreground": "#E2E8F0",
                "accent": "#22D3EE",
                "muted": "#94A3B8",
            },
            "fonts": {"title": "Playfair Display", "body": "IBM Plex Sans"},
        },
    },
]

TEMPLATE_ALIASES: dict[str, str] = {
    "clean_academic": "academic_evidence",
    "data_story": "executive_data_story",
    "executive_impact": "executive_data_story",
    "workshop_active": "academic_evidence",
    "minimal_mono": "academic_evidence",
    "professional_showcase": "professional_showcase",
}


TEMPLATE_STYLE_GUIDES: dict[str, dict[str, Any]] = {
    "academic_evidence": {
        "tone": "structured academic evidence",
        "density_target": "medium",
        "asset_voice": "scholarly diagrams with explicit source annotation",
    },
    "executive_data_story": {
        "tone": "executive evidence storytelling",
        "density_target": "medium-low",
        "asset_voice": "board-ready charts, KPI highlights, concise decision visuals",
    },
    "professional_showcase": {
        "tone": "premium showcase",
        "density_target": "medium",
        "asset_voice": "hero visuals with polished backgrounds and metric highlights",
    },
}


def _slot(x: int, y: int, w: int, h: int) -> dict[str, int]:
    return {"x": x, "y": y, "w": w, "h": h, "rot": 0}


LAYOUT_VARIANTS: list[dict[str, Any]] = [
    {
        "id": "hero_split_left",
        "description": "Narrative block on left, visual and chart stack on right.",
        "chart_type": "bar",
        "svg_variant": "professional",
        "metric_cards": 0,
        "constraints": {"max_bullets": 4, "max_line_chars": 88, "min_chart_h": 240},
        "slots": {
            "title": _slot(86, 74, 780, 132),
            "objective": _slot(92, 214, 760, 78),
            "bullets": _slot(96, 306, 740, 376),
            "callout": _slot(96, 706, 740, 136),
            "image": _slot(916, 106, 610, 330),
            "chart": _slot(916, 456, 610, 322),
        },
    },
    {
        "id": "hero_split_right",
        "description": "Visual block on left, narrative and chart stack on right.",
        "chart_type": "line",
        "svg_variant": "data_story",
        "metric_cards": 0,
        "constraints": {"max_bullets": 4, "max_line_chars": 86, "min_chart_h": 220},
        "slots": {
            "title": _slot(760, 72, 750, 128),
            "objective": _slot(764, 206, 730, 76),
            "bullets": _slot(768, 294, 710, 386),
            "callout": _slot(768, 704, 710, 136),
            "image": _slot(86, 100, 640, 370),
            "chart": _slot(98, 500, 620, 292),
        },
    },
    {
        "id": "top_visual",
        "description": "Large visual on top, supporting bullets and chart below.",
        "chart_type": "bar",
        "svg_variant": "workshop",
        "metric_cards": 0,
        "constraints": {"max_bullets": 4, "max_line_chars": 76, "min_chart_h": 190},
        "slots": {
            "title": _slot(84, 56, 1300, 106),
            "objective": _slot(90, 168, 1240, 66),
            "image": _slot(90, 248, 960, 356),
            "bullets": _slot(1080, 252, 430, 350),
            "chart": _slot(92, 626, 650, 226),
            "callout": _slot(770, 626, 740, 226),
        },
    },
    {
        "id": "data_dashboard",
        "description": "Dashboard-style slide with dual charts and concise narrative.",
        "chart_type": "bar",
        "svg_variant": "data_story",
        "metric_cards": 3,
        "constraints": {"max_bullets": 3, "max_line_chars": 70, "min_chart_h": 220},
        "slots": {
            "title": _slot(84, 58, 980, 102),
            "objective": _slot(90, 166, 940, 62),
            "bullets": _slot(1032, 248, 492, 286),
            "chart": _slot(88, 248, 892, 286),
            "chart_secondary": _slot(88, 552, 892, 278),
            "image": _slot(1032, 548, 492, 280),
        },
    },
    {
        "id": "timeline_flow",
        "description": "Timeline-inspired flow with milestones and summary chart.",
        "chart_type": "line",
        "svg_variant": "executive",
        "metric_cards": 0,
        "constraints": {"max_bullets": 4, "max_line_chars": 84, "min_chart_h": 220},
        "slots": {
            "title": _slot(84, 54, 1180, 110),
            "objective": _slot(90, 170, 1120, 66),
            "bullets": _slot(90, 528, 740, 300),
            "image": _slot(882, 248, 626, 244),
            "chart": _slot(882, 516, 626, 314),
            "callout": _slot(90, 252, 748, 250),
        },
    },
    {
        "id": "comparison_dual",
        "description": "Two-column comparison with center visual anchor.",
        "chart_type": "bar",
        "svg_variant": "default",
        "metric_cards": 0,
        "constraints": {"max_bullets": 4, "max_line_chars": 82, "min_chart_h": 190},
        "slots": {
            "title": _slot(84, 54, 1220, 106),
            "objective": _slot(90, 168, 1180, 66),
            "bullets": _slot(94, 248, 612, 356),
            "image": _slot(742, 252, 774, 318),
            "chart": _slot(94, 624, 1422, 220),
            "callout": _slot(742, 560, 774, 56),
        },
    },
    {
        "id": "focus_statement",
        "description": "Big statement + supporting assets for high-impact messaging.",
        "chart_type": "line",
        "svg_variant": "professional",
        "metric_cards": 2,
        "constraints": {"max_bullets": 1, "max_line_chars": 64, "min_chart_h": 230},
        "slots": {
            "title": _slot(94, 80, 1410, 138),
            "objective": _slot(100, 228, 1320, 70),
            "callout": _slot(100, 316, 1320, 164),
            "image": _slot(98, 506, 700, 308),
            "chart": _slot(828, 506, 676, 308),
            "bullets": _slot(100, 826, 1404, 64),
        },
    },
    {
        "id": "workshop_cards",
        "description": "Card-led layout suitable for collaborative, activity-driven content.",
        "chart_type": "bar",
        "svg_variant": "workshop",
        "metric_cards": 3,
        "constraints": {"max_bullets": 4, "max_line_chars": 78, "min_chart_h": 200},
        "slots": {
            "title": _slot(82, 56, 990, 108),
            "objective": _slot(88, 170, 940, 66),
            "bullets": _slot(92, 252, 700, 302),
            "image": _slot(820, 252, 704, 300),
            "chart": _slot(92, 578, 700, 262),
            "callout": _slot(820, 578, 704, 262),
        },
    },
]


TEMPLATE_LAYOUT_POOLS: dict[str, list[str]] = {
    "academic_evidence": [
        "hero_split_left",
        "timeline_flow",
        "focus_statement",
        "workshop_cards",
    ],
    "executive_data_story": [
        "data_dashboard",
        "hero_split_left",
        "comparison_dual",
        "top_visual",
        "timeline_flow",
    ],
    "professional_showcase": [
        "focus_statement",
        "hero_split_left",
        "hero_split_right",
        "data_dashboard",
        "top_visual",
    ],
}


def _template_map() -> dict[str, dict[str, Any]]:
    return {template["id"]: template for template in STYLE_PRESETS}


def _layout_map() -> dict[str, dict[str, Any]]:
    return {layout["id"]: layout for layout in LAYOUT_VARIANTS}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
    return default


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _slide_count(settings: dict[str, Any]) -> int:
    raw_count = _as_int(settings.get("slide_count"), 10)
    return int(_clamp(raw_count, 3, 24))


def _instruction_max_loops(settings: dict[str, Any]) -> int:
    raw = _as_int(settings.get("max_instruction_loops"), 5)
    return int(_clamp(raw, 1, 20))


def _preferred_pro_model() -> str | None:
    for key in ("PRO_MODEL", "SLIDE_PRO_MODEL"):
        model = (os.getenv(key) or "").strip()
        if model:
            return model
    return None


def _preferred_image_model() -> str | None:
    image_model = (os.getenv("IMAGE_MODEL") or "").strip()
    if image_model:
        return image_model
    return None


def _template_id(settings: dict[str, Any]) -> str:
    template_id = str(settings.get("template_id") or settings.get("style") or "academic_evidence")
    normalized = template_id.strip().lower().replace("-", "_").replace(" ", "_")
    normalized = TEMPLATE_ALIASES.get(normalized, normalized)
    templates = _template_map()
    return normalized if normalized in templates else "academic_evidence"


def _default_theme(template_id: str) -> dict[str, Any]:
    return _template_map().get(template_id, _template_map()["academic_evidence"])["theme"]


def _short_lines(text: str, limit: int = 5) -> list[str]:
    parts = [line.strip() for line in re.split(r"[\n;]+", text) if line.strip()]
    return parts[:limit]


def _trim_sentence(text: str, max_chars: int) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= max_chars:
        return clean
    truncated = clean[:max_chars].rsplit(" ", 1)[0].strip()
    return truncated or clean[:max_chars].strip()


def _coerce_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        lines = [_coerce_text(item) for item in value]
        return "\n".join(line for line in lines if line).strip()
    if isinstance(value, dict):
        for key in (
            "markdown",
            "normalized_text",
            "text",
            "content",
            "summary",
            "description",
            "notes",
            "answer",
        ):
            candidate = _coerce_text(value.get(key))
            if candidate:
                return candidate
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return ""
    return ""


def _records_to_source_context(source_records: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for record in source_records:
        if not isinstance(record, dict):
            continue
        title = _coerce_text(record.get("title")) or "Untitled"
        record_type = (_coerce_text(record.get("type")) or "record").upper()
        query = _coerce_text(record.get("user_query"))
        output = _coerce_text(record.get("output"))
        metadata = record.get("metadata")
        if not output and isinstance(metadata, dict):
            output = (
                _coerce_text(metadata.get("markdown"))
                or _coerce_text(metadata.get("normalized_text"))
                or _coerce_text(metadata.get("text"))
                or _coerce_text(metadata.get("notes"))
                or _coerce_text(metadata.get("content"))
            )

        lines = [f"## {title}", f"Type: {record_type}"]
        if query:
            lines.extend(["", f"Prompt: {query}"])
        if output:
            lines.extend(["", output])
        else:
            lines.extend(["", "(No textual output found in this record.)"])
        chunks.append("\n".join(lines))
    return "\n\n---\n\n".join(chunks).strip()


def _stable_seed(text: str) -> int:
    state = 2166136261
    for ch in text:
        state ^= ord(ch)
        state = (state * 16777619) & 0xFFFFFFFF
    return state or 1


def _lcg_values(seed: int, count: int, min_value: float = 0.0, max_value: float = 1.0) -> list[float]:
    state = seed & 0xFFFFFFFF
    span = max_value - min_value
    values: list[float] = []
    for _ in range(count):
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        ratio = state / 4294967296.0
        values.append(min_value + (ratio * span))
    return values


def _normalize_key_points(
    points: list[Any],
    max_items: int = 5,
    fallback_subject: str = "",
) -> list[str]:
    normalized: list[str] = []
    for item in points:
        text = _trim_sentence(_coerce_text(item), 140)
        if text:
            normalized.append(text)
        if len(normalized) >= max_items:
            break
    if not normalized:
        subject = _trim_sentence(_coerce_text(fallback_subject), 72)
        if not subject:
            normalized = [
                "Define the baseline and scope clearly.",
                "Highlight the strongest supporting signal.",
                "Conclude with concrete implications.",
            ]
        else:
            normalized = [
                _trim_sentence(f"Baseline of {subject}.", 140),
                _trim_sentence(f"Key evidence around {subject}.", 140),
                _trim_sentence(f"Implications and next steps for {subject}.", 140),
            ]
    return normalized


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(key)
    return output


def _keyword_label(text: str, fallback: str) -> str:
    tokens = [tok for tok in re.split(r"[^a-zA-Z0-9]+", text) if tok]
    if not tokens:
        return fallback
    word = tokens[0][:8].upper()
    return word or fallback


def _chart_values_from_points(points: list[str], seed: int, count: int = 5) -> list[int]:
    noise = _lcg_values(seed, count, 0.0, 3.0)
    values: list[int] = []
    for idx in range(count):
        point = points[idx % len(points)] if points else f"metric-{idx+1}"
        base = 3 + min(7, max(1, len(point.split()) // 2))
        values.append(int(_clamp(base + noise[idx], 2, 12)))
    return values


def _contains_data_claim(text: str) -> bool:
    cleaned = _coerce_text(text)
    if not cleaned:
        return False
    pattern = re.compile(
        r"(\d+(\.\d+)?\s*%|\d+(\.\d+)?|top\s*\d+|x\d+|times|benchmark|accuracy|latency|score)",
        re.IGNORECASE,
    )
    return bool(pattern.search(cleaned))


def _is_claim_element_for_citation(element: dict[str, Any]) -> bool:
    if not isinstance(element, dict):
        return False
    element_type = _coerce_text(element.get("type")).lower()
    if element_type in {"bullets", "chart", "table"}:
        return True
    style = element.get("style", {}) if isinstance(element.get("style"), dict) else {}
    purpose = _coerce_text(style.get("purpose")).lower()
    if element_type == "shape":
        return purpose == "chart_fallback"
    if element_type == "text":
        element_id = _coerce_text(element.get("id")).lower()
        if element_id.endswith("_title"):
            return False
        if purpose in {"background", "decor"}:
            return False
        return True
    return False


def _normalize_hex_color(value: Any, fallback: str = "#0F172A") -> str:
    raw = _coerce_text(value)
    if not raw:
        return fallback
    raw = raw.strip()
    if not raw.startswith("#"):
        raw = f"#{raw}"
    if re.fullmatch(r"#[0-9a-fA-F]{6}", raw):
        return raw.upper()
    if re.fullmatch(r"#[0-9a-fA-F]{8}", raw):
        return raw[:7].upper()
    return fallback


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    normalized = _normalize_hex_color(value)
    return (
        int(normalized[1:3], 16),
        int(normalized[3:5], 16),
        int(normalized[5:7], 16),
    )


def _relative_luminance(color: str) -> float:
    rgb = _hex_to_rgb(color)
    channels = []
    for ch in rgb:
        c = ch / 255.0
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    fg = _relative_luminance(foreground)
    bg = _relative_luminance(background)
    light = max(fg, bg)
    dark = min(fg, bg)
    return (light + 0.05) / (dark + 0.05)


def _blend_hex(foreground: str, background: str, alpha: float) -> str:
    fg = _hex_to_rgb(foreground)
    bg = _hex_to_rgb(background)
    ratio = _clamp(alpha, 0.0, 1.0)
    mixed = [
        int(round((fg[idx] * ratio) + (bg[idx] * (1.0 - ratio))))
        for idx in range(3)
    ]
    return f"#{mixed[0]:02X}{mixed[1]:02X}{mixed[2]:02X}"


_METRIC_HINT_TOKENS = {
    "%",
    "percent",
    "accuracy",
    "precision",
    "recall",
    "f1",
    "score",
    "rate",
    "latency",
    "throughput",
    "speed",
    "runtime",
    "error",
    "loss",
    "auc",
    "map",
    "iou",
    "fps",
    "ms",
    "sec",
    "seconds",
    "minute",
    "minutes",
    "hour",
    "hours",
    "times",
    "million",
    "billion",
}

_NON_METRIC_HINT_TOKENS = {
    "page",
    "pages",
    "pp.",
    "pp",
    "lecture",
    "chapter",
    "section",
    "slide",
    "source",
    "ref",
    "citation",
    "doc",
    "document",
    "kb",
}


def _extract_numeric_values(text: str, max_values: int = 8) -> list[float]:
    cleaned = _coerce_text(text)
    if not cleaned:
        return []
    values: list[float] = []
    for match in re.finditer(r"(?<![\w.])(\d{1,4}(?:\.\d+)?)(\s*%?)", cleaned):
        raw_value = _coerce_text(match.group(1))
        unit = _coerce_text(match.group(2))
        if not raw_value:
            continue
        value = _as_float(raw_value, float("nan"))
        if not isinstance(value, float) or value != value:  # NaN-safe check
            continue
        if unit.strip() == "%":
            values.append(_clamp(value, 0.0, 100.0))
        else:
            values.append(_clamp(value, 0.0, 10000.0))
        if len(values) >= max_values:
            break
    return values


def _extract_metric_values(text: str, max_values: int = 8) -> list[float]:
    cleaned = _coerce_text(text)
    if not cleaned:
        return []

    lowered = cleaned.lower()
    values: list[float] = []
    for match in re.finditer(r"(?<![\w.])(\d{1,4}(?:\.\d+)?)(\s*%?)", cleaned):
        raw_value = _coerce_text(match.group(1))
        unit = _coerce_text(match.group(2))
        if not raw_value:
            continue
        value = _as_float(raw_value, float("nan"))
        if not isinstance(value, float) or value != value:  # NaN-safe check
            continue

        start = max(0, match.start() - 24)
        end = min(len(lowered), match.end() + 24)
        context = lowered[start:end]
        has_metric_hint = any(token in context for token in _METRIC_HINT_TOKENS)
        has_non_metric_hint = any(token in context for token in _NON_METRIC_HINT_TOKENS)
        is_percent = unit.strip() == "%"

        # Reject likely index/page/course identifiers unless explicitly metric.
        if not is_percent:
            if has_non_metric_hint and not has_metric_hint:
                continue
            if value <= 15 and not has_metric_hint:
                continue

        normalized_value = value * 100.0 if (0.0 < value < 1.0 and has_metric_hint) else value
        if is_percent:
            normalized_value = _clamp(normalized_value, 0.0, 100.0)
        else:
            normalized_value = _clamp(normalized_value, 0.0, 10000.0)

        values.append(normalized_value)
        if len(values) >= max_values:
            break
    return values


def _metric_labels_from_texts(texts: list[str], max_labels: int = 5) -> list[str]:
    labels: list[str] = []
    for text in texts:
        lowered = _coerce_text(text).lower()
        if not lowered:
            continue
        for token in (
            "accuracy",
            "precision",
            "recall",
            "f1",
            "auc",
            "map",
            "iou",
            "latency",
            "throughput",
            "error",
            "loss",
            "runtime",
            "speed",
            "score",
            "rate",
        ):
            if token in lowered:
                candidate = token.upper()
                if candidate not in labels:
                    labels.append(candidate)
                break
        if len(labels) >= max_labels:
            break
    return labels


def _line_capacity(box_width: int, font_size: float) -> int:
    width = max(120, _as_int(box_width, 120))
    size = max(12.0, _as_float(font_size, 24.0))
    return int(_clamp(width / max(6.2, size * 0.53), 14.0, 180.0))


def _estimated_wrapped_line_count(lines: list[str], box_width: int, font_size: float) -> int:
    capacity = _line_capacity(box_width, font_size)
    wrapped = 0
    for line in lines:
        text = _coerce_text(line)
        if not text:
            continue
        wrapped += max(1, int((len(text) + capacity - 1) // capacity))
    return wrapped


def _estimate_text_overflow(element: dict[str, Any]) -> bool:
    if not isinstance(element, dict):
        return False
    element_type = _coerce_text(element.get("type"))
    if element_type not in {"text", "bullets", "equation"}:
        return False
    box = element.get("box", {}) if isinstance(element.get("box"), dict) else {}
    style = element.get("style", {}) if isinstance(element.get("style"), dict) else {}
    font_size = max(10.0, _as_float(style.get("fontSize"), 24.0))
    line_height = _clamp(_as_float(style.get("lineHeight"), 1.24), 1.0, 1.8)
    box_h = max(40.0, _as_float(box.get("h"), 60.0))
    lines_raw = element.get("content")
    lines = (
        [_coerce_text(item) for item in lines_raw]
        if isinstance(lines_raw, list)
        else [_coerce_text(lines_raw)] if _coerce_text(lines_raw) else []
    )
    if not lines:
        return False
    wrapped_lines = _estimated_wrapped_line_count(lines, _as_int(box.get("w"), 240), font_size)
    line_capacity = box_h / max(10.0, font_size * line_height)
    # Keep a small breathing room to avoid clipping in PPT renderers.
    return wrapped_lines > (line_capacity - 0.25)


def _boxes_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ax = _as_float(a.get("x"), 0.0)
    ay = _as_float(a.get("y"), 0.0)
    aw = max(0.0, _as_float(a.get("w"), 0.0))
    ah = max(0.0, _as_float(a.get("h"), 0.0))
    bx = _as_float(b.get("x"), 0.0)
    by = _as_float(b.get("y"), 0.0)
    bw = max(0.0, _as_float(b.get("w"), 0.0))
    bh = max(0.0, _as_float(b.get("h"), 0.0))
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return False
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def _chart_data_for_slide(
    title: str,
    key_points: list[str],
    seed: int,
    citations: list[dict[str, Any]] | None = None,
    allow_synthetic: bool = False,
) -> dict[str, Any]:
    labels: list[str] = []
    grounded_values: list[float] = []
    label_sources: list[str] = []

    for point in key_points:
        text = _coerce_text(point)
        if not text:
            continue
        label_sources.append(text)
        grounded_values.extend(_extract_metric_values(text, max_values=2))

    for citation in citations or []:
        if len(grounded_values) >= 6:
            break
        if not isinstance(citation, dict):
            continue
        snippet = _coerce_text(citation.get("snippet"))
        if snippet:
            label_sources.append(snippet)
            grounded_values.extend(_extract_metric_values(snippet, max_values=3))

    if grounded_values:
        usable_count = min(5, len(grounded_values))
        usable = [int(round(_clamp(value, 0.0, 100.0))) for value in grounded_values[:usable_count]]
        if len(usable) < 3:
            return {
                "labels": ["Metric 1", "Metric 2", "Metric 3"],
                "series": [],
                "grounded": False,
                "reason": "insufficient_numeric_evidence",
            }
        labels = _metric_labels_from_texts(label_sources, max_labels=usable_count)
        while len(labels) < usable_count:
            labels.append(f"Metric {len(labels) + 1}")
        return {
            "labels": labels[: len(usable)],
            "series": [{"name": "Observed", "values": usable}],
            "grounded": True,
            "reason": "",
        }

    if allow_synthetic:
        if len(labels) < 3:
            labels = [f"M{idx + 1}" for idx in range(3)]
        values = _chart_values_from_points(key_points or [title], seed, count=5)
        return {
            "labels": labels[: len(values)],
            "series": [{"name": "Trend", "values": values}],
            "grounded": False,
            "reason": "synthetic",
        }

    return {
        "labels": ["Metric 1", "Metric 2", "Metric 3"],
        "series": [],
        "grounded": False,
        "reason": "insufficient_numeric_evidence",
    }


def _make_svg_data_url(
    title: str,
    accent: str,
    background: str,
    *,
    variant: str = "default",
    foreground: str = "#0F172A",
    prompt: str = "",
    seed: int = 1,
) -> str:
    safe_title = re.sub(r"[<>&\"]", " ", title)[:56] or "Slide Asset"
    safe_prompt = re.sub(r"[<>&\"]", " ", prompt)[:74]
    values = _lcg_values(seed, 10, 0.0, 1.0)
    x1 = int(90 + values[0] * 90)
    y1 = int(82 + values[1] * 88)
    x2 = int(540 + values[2] * 160)
    y2 = int(88 + values[3] * 88)
    bar_a = int(56 + values[4] * 130)
    bar_b = int(56 + values[5] * 130)
    bar_c = int(56 + values[6] * 130)
    bar_d = int(56 + values[7] * 130)
    bar_e = int(56 + values[8] * 130)

    if variant == "data_story":
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='450' viewBox='0 0 800 450'>"
            f"<rect width='800' height='450' rx='28' fill='{background}'/>"
            f"<rect x='44' y='54' width='712' height='338' rx='18' fill='{accent}' fill-opacity='0.14'/>"
            f"<circle cx='{x1}' cy='{y1}' r='36' fill='{accent}' fill-opacity='0.18'/>"
            f"<circle cx='{x2}' cy='{y2}' r='42' fill='{accent}' fill-opacity='0.22'/>"
            f"<rect x='104' y='{332-bar_a}' width='62' height='{bar_a}' rx='8' fill='{accent}' fill-opacity='0.75'/>"
            f"<rect x='190' y='{332-bar_b}' width='62' height='{bar_b}' rx='8' fill='{accent}' fill-opacity='0.83'/>"
            f"<rect x='276' y='{332-bar_c}' width='62' height='{bar_c}' rx='8' fill='{accent}' fill-opacity='0.88'/>"
            f"<rect x='362' y='{332-bar_d}' width='62' height='{bar_d}' rx='8' fill='{accent}' fill-opacity='0.81'/>"
            f"<rect x='448' y='{332-bar_e}' width='62' height='{bar_e}' rx='8' fill='{accent}' fill-opacity='0.93'/>"
            f"<text x='400' y='118' text-anchor='middle' font-size='34' fill='{foreground}'"
            " font-family='IBM Plex Sans, Arial, sans-serif' font-weight='700'>"
            f"{safe_title}</text>"
            f"<text x='400' y='156' text-anchor='middle' font-size='17' fill='{foreground}' fill-opacity='0.78'"
            " font-family='IBM Plex Sans, Arial, sans-serif'>"
            f"{safe_prompt or 'Evidence-focused visual summary'}</text></svg>"
        )
    elif variant == "executive":
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='450' viewBox='0 0 800 450'>"
            f"<rect width='800' height='450' rx='28' fill='{background}'/>"
            f"<rect x='520' y='0' width='280' height='450' fill='{accent}' fill-opacity='0.19'/>"
            f"<circle cx='640' cy='{96 + int(values[0]*120)}' r='82' fill='{accent}' fill-opacity='0.31'/>"
            f"<rect x='66' y='88' width='378' height='58' rx='10' fill='{accent}' fill-opacity='0.16'/>"
            f"<rect x='66' y='176' width='372' height='42' rx='10' fill='{accent}' fill-opacity='0.11'/>"
            f"<rect x='66' y='246' width='350' height='42' rx='10' fill='{accent}' fill-opacity='0.09'/>"
            f"<text x='252' y='120' text-anchor='middle' font-size='30' fill='{foreground}'"
            " font-family='Fraunces, Georgia, serif' font-weight='700'>"
            f"{safe_title}</text>"
            f"<text x='252' y='154' text-anchor='middle' font-size='16' fill='{foreground}' fill-opacity='0.75'"
            " font-family='Manrope, Arial, sans-serif'>"
            f"{safe_prompt or 'Insight snapshot'}</text></svg>"
        )
    elif variant == "workshop":
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='450' viewBox='0 0 800 450'>"
            f"<rect width='800' height='450' rx='28' fill='{background}'/>"
            "<rect x='72' y='84' width='200' height='140' rx='16' fill='#FEF3C7'/>"
            "<rect x='298' y='84' width='200' height='140' rx='16' fill='#DBEAFE'/>"
            "<rect x='524' y='84' width='200' height='140' rx='16' fill='#DCFCE7'/>"
            f"<rect x='72' y='256' width='652' height='118' rx='20' fill='{accent}' fill-opacity='0.14'/>"
            f"<circle cx='{x1}' cy='{y1}' r='26' fill='{accent}' fill-opacity='0.24'/>"
            f"<circle cx='{x2}' cy='{y2}' r='18' fill='{accent}' fill-opacity='0.18'/>"
            f"<text x='400' y='316' text-anchor='middle' font-size='34' fill='{foreground}'"
            " font-family='Space Grotesk, Arial, sans-serif' font-weight='700'>"
            f"{safe_title}</text>"
            f"<text x='400' y='352' text-anchor='middle' font-size='16' fill='{foreground}' fill-opacity='0.75'"
            " font-family='IBM Plex Sans, Arial, sans-serif'>"
            f"{safe_prompt or 'Visual concept map'}</text></svg>"
        )
    elif variant == "professional":
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='450' viewBox='0 0 800 450'>"
            f"<rect width='800' height='450' rx='28' fill='{background}'/>"
            "<defs><linearGradient id='g1' x1='0' x2='1' y1='0' y2='1'>"
            f"<stop offset='0%' stop-color='{accent}' stop-opacity='0.44'/>"
            f"<stop offset='100%' stop-color='{accent}' stop-opacity='0.08'/>"
            "</linearGradient></defs>"
            "<path d='M0,330 C170,250 310,370 520,280 C640,230 720,170 800,110 L800,450 L0,450 Z' fill='url(#g1)'/>"
            f"<circle cx='614' cy='{86 + int(values[2]*80)}' r='78' fill='{accent}' fill-opacity='0.27'/>"
            f"<rect x='76' y='86' width='444' height='82' rx='16' fill='{accent}' fill-opacity='0.18'/>"
            f"<rect x='76' y='188' width='372' height='46' rx='10' fill='{accent}' fill-opacity='0.12'/>"
            f"<rect x='76' y='252' width='328' height='46' rx='10' fill='{accent}' fill-opacity='0.12'/>"
            f"<text x='298' y='132' text-anchor='middle' font-size='34' fill='{foreground}'"
            " font-family='Playfair Display, Georgia, serif' font-weight='700'>"
            f"{safe_title}</text>"
            f"<text x='298' y='168' text-anchor='middle' font-size='16' fill='{foreground}' fill-opacity='0.76'"
            " font-family='IBM Plex Sans, Arial, sans-serif'>"
            f"{safe_prompt or 'Visual concept map'}</text></svg>"
        )
    else:
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='450' viewBox='0 0 800 450'>"
            f"<rect width='800' height='450' rx='30' fill='{background}'/>"
            f"<circle cx='{x1}' cy='{y1}' r='62' fill='{accent}' fill-opacity='0.19'/>"
            f"<rect x='90' y='170' width='620' height='180' rx='20' fill='{accent}' fill-opacity='0.11'/>"
            f"<text x='400' y='246' text-anchor='middle' font-size='34' fill='{foreground}'"
            " font-family='Segoe UI, Arial, sans-serif' font-weight='700'>"
            f"{safe_title}</text>"
            f"<text x='400' y='284' text-anchor='middle' font-size='17' fill='{foreground}' fill-opacity='0.78'"
            " font-family='Segoe UI, Arial, sans-serif'>"
            f"{safe_prompt or 'Key visual reference'}</text></svg>"
        )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


class SlideResearchAgent:
    @staticmethod
    def _source_is_sparse(source_text: str) -> bool:
        compact = source_text.strip()
        if not compact:
            return True
        non_empty_lines = [line.strip() for line in compact.splitlines() if line.strip()]
        return len(compact) < 320 or len(non_empty_lines) < 3

    @staticmethod
    def _build_query(title: str, source_text: str, instructions: str, language: str) -> str:
        language_tag = "Vietnamese" if language == "vi" else "English"
        candidates = _short_lines(source_text, limit=2)
        seed = candidates[0] if candidates else (instructions.strip() or title.strip() or "topic overview")
        return _trim_sentence(f"{title or 'Slide topic'} {seed} ({language_tag})", 180)

    @staticmethod
    def _query_budget(effort: str) -> int:
        if effort == "high":
            return 3
        if effort == "fast":
            return 1
        return 2

    @staticmethod
    def _build_queries(
        title: str,
        source_text: str,
        instructions: str,
        language: str,
        effort: str,
    ) -> list[str]:
        language_tag = "Vietnamese" if language == "vi" else "English"
        budget = SlideResearchAgent._query_budget(effort)
        topic = _trim_sentence(title.strip() or "Slide topic", 90)
        seeds = _dedupe_keep_order(
            [
                _trim_sentence(item, 130)
                for item in (
                    [instructions.strip()] + _short_lines(source_text, limit=8)
                )
                if _trim_sentence(item, 130)
            ]
        )

        queries = [
            _trim_sentence(
                f"{topic} core concepts evidence-backed findings and practical implications ({language_tag})",
                180,
            )
        ]
        for seed in seeds:
            if len(queries) >= budget:
                break
            queries.append(
                _trim_sentence(
                    f"{topic} {seed} quantitative evidence limitations applications ({language_tag})",
                    180,
                )
            )
        while len(queries) < budget:
            queries.append(
                _trim_sentence(
                    f"{topic} modern methods benchmarks challenges and real-world use ({language_tag})",
                    180,
                )
            )
        return _dedupe_keep_order(queries[:budget])

    @staticmethod
    def _normalize_effort(value: Any) -> str:
        normalized = _coerce_text(value).strip().lower()
        if normalized in {"fast", "medium", "high"}:
            return normalized
        return "medium"

    @staticmethod
    def _normalize_kb_names(settings: dict[str, Any]) -> list[str]:
        raw = settings.get("kb_names")
        names: list[str] = []
        if isinstance(raw, list):
            names = [_coerce_text(item) for item in raw]
        elif isinstance(raw, str):
            names = [segment.strip() for segment in re.split(r"[,\n;]+", raw) if segment.strip()]

        if not names:
            single = _coerce_text(settings.get("kb_name"))
            if single:
                names = [single]
        return _dedupe_keep_order([name for name in names if name])

    @staticmethod
    def _available_kb_names() -> tuple[list[str], str | None]:
        try:
            from src.knowledge.manager import KnowledgeBaseManager
        except Exception as exc:
            return [], f"Knowledge manager import failed: {exc}"

        try:
            project_root = Path(__file__).resolve().parent.parent.parent.parent
            manager = KnowledgeBaseManager(base_dir=str(project_root / "data" / "knowledge_bases"))
            return manager.list_knowledge_bases(), None
        except Exception as exc:
            return [], f"Failed to list knowledge bases: {exc}"

    @staticmethod
    def _default_kb_name(candidates: list[str]) -> str:
        if not candidates:
            return ""
        try:
            from src.services.config import get_kb_config_service

            default_kb = _coerce_text(get_kb_config_service().get_default_kb())
            if default_kb and default_kb in candidates:
                return default_kb
        except Exception:
            pass
        return candidates[0]

    @staticmethod
    def _kb_runtime_config(kb_name: str) -> dict[str, str]:
        fallback = {
            "search_mode": "hybrid",
            "retrieval_profile": "standard",
            "rag_provider": "unknown",
        }
        try:
            from src.services.config import get_kb_config_service

            kb_cfg = get_kb_config_service().get_kb_config(kb_name)
            fallback["search_mode"] = _coerce_text(kb_cfg.get("search_mode")) or "hybrid"
            fallback["retrieval_profile"] = (
                _coerce_text(kb_cfg.get("retrieval_profile")) or "standard"
            )
            fallback["rag_provider"] = _coerce_text(kb_cfg.get("rag_provider")) or "unknown"
            return fallback
        except Exception:
            return fallback

    @staticmethod
    def _default_search_provider() -> str:
        try:
            from src.services.search import get_current_config

            current = get_current_config()
            provider = _coerce_text(current.get("provider")).lower()
            return provider or "perplexity"
        except Exception:
            return "perplexity"

    @staticmethod
    def _web_kwargs_for_effort(provider: str, effort: str) -> dict[str, Any]:
        effort_rank = {"fast": 0, "medium": 1, "high": 2}
        level = effort_rank.get(effort, 1)
        count_map = {0: 5, 1: 8, 2: 12}
        result_count = count_map[level]

        if provider == "tavily":
            return {
                "search_depth": "advanced" if effort == "high" else "basic",
                "max_results": result_count,
                "include_answer": True,
            }
        if provider == "serper":
            return {"mode": "search", "num": result_count, "gl": "us", "hl": "en"}
        if provider == "exa":
            return {
                "search_type": "neural" if effort == "high" else "auto",
                "num_results": result_count,
                "include_summary": True,
                "include_highlights": effort != "fast",
            }
        if provider == "jina":
            return {"enrich": effort != "fast"}
        if provider == "baidu":
            recency = "week" if effort == "fast" else "month" if effort == "medium" else "year"
            return {
                "enable_deep_search": effort == "high",
                "search_recency_filter": recency,
            }
        if provider == "perplexity":
            model = "sonar"
            if effort == "high":
                model = "sonar-pro"
            return {"model": model}
        return {}

    @staticmethod
    def _search_web(
        query: str,
        provider: str,
        effort: str,
    ) -> tuple[dict[str, Any] | None, str | None]:
        try:
            from src.services.search import web_search
        except Exception as exc:
            return None, f"Web search import failed: {exc}"

        def normalize_web_citations(raw_items: Any) -> list[dict[str, Any]]:
            normalized: list[dict[str, Any]] = []
            if not isinstance(raw_items, list):
                return normalized
            for item in raw_items[:8]:
                if not isinstance(item, dict):
                    continue
                url = _coerce_text(item.get("url"))
                title = _trim_sentence(
                    _coerce_text(item.get("title") or item.get("source") or url or "Web source"),
                    180,
                )
                snippet = _trim_sentence(
                    _coerce_text(item.get("snippet") or item.get("content")),
                    220,
                )
                source = _trim_sentence(_coerce_text(item.get("source") or item.get("website")), 80)
                date = _coerce_text(item.get("date"))
                if not (title or url):
                    continue
                normalized.append(
                    {
                        "source_type": "web",
                        "title": title or url,
                        "url": url,
                        "source": source,
                        "date": date,
                        "snippet": snippet,
                    }
                )
            return normalized

        kwargs = SlideResearchAgent._web_kwargs_for_effort(provider, effort)
        try:
            started = time.perf_counter()
            result = web_search(query=query, provider=provider or None, **kwargs)
            latency_ms = int((time.perf_counter() - started) * 1000)
            answer = _trim_sentence(_coerce_text(result.get("answer")), 900)
            citations = normalize_web_citations(result.get("citations") or [])
            provider_used = _coerce_text(result.get("provider")) or provider
            if answer and not citations:
                citations = [
                    {
                        "source_type": "web",
                        "title": _trim_sentence(f"{provider_used} retrieval for: {query}", 180),
                        "url": "",
                        "source": provider_used,
                        "date": "",
                        "snippet": _trim_sentence(answer, 220),
                    }
                ]
            return (
                {
                    "answer": answer,
                    "citations": citations,
                    "provider": provider_used,
                    "effort": effort,
                    "latency_ms": latency_ms,
                },
                None,
            )
        except Exception as exc:
            return None, f"Web search failed: {exc}"

    @staticmethod
    async def _search_kb(
        query: str,
        kb_name: str,
        *,
        search_mode: str,
        retrieval_profile: str,
    ) -> tuple[dict[str, Any] | None, str | None, int]:
        try:
            from src.services.rag import RAGService
        except Exception as exc:
            return None, f"KB search import failed: {exc}", 0

        def normalize_kb_citations(raw_items: Any) -> list[dict[str, Any]]:
            normalized: list[dict[str, Any]] = []
            if not isinstance(raw_items, list):
                return normalized
            for item in raw_items[:10]:
                if not isinstance(item, dict):
                    continue
                doc_name = _trim_sentence(_coerce_text(item.get("doc_name")), 120)
                page_start = _as_int(item.get("page_start"), 0)
                page_end = _as_int(item.get("page_end"), page_start)
                section_path = _trim_sentence(_coerce_text(item.get("section_path")), 120)
                chunk_id = _coerce_text(item.get("chunk_id"))
                short_ref = doc_name or kb_name
                if page_start > 0 and page_end > 0:
                    short_ref = (
                        f"{short_ref}, p.{page_start}"
                        if page_start == page_end
                        else f"{short_ref}, pp.{page_start}-{page_end}"
                    )
                normalized.append(
                    {
                        "source_type": "kb",
                        "title": short_ref,
                        "kb_name": kb_name,
                        "doc_name": doc_name or kb_name,
                        "page_start": page_start if page_start > 0 else None,
                        "page_end": page_end if page_end > 0 else None,
                        "section_path": section_path,
                        "chunk_id": chunk_id,
                        "snippet": _trim_sentence(_coerce_text(item.get("text") or item.get("summary")), 220),
                    }
                )
            return normalized

        try:
            started = time.perf_counter()
            service = RAGService()
            result = await service.search(query=query, kb_name=kb_name, mode=search_mode)
            latency_ms = int((time.perf_counter() - started) * 1000)
            text = _trim_sentence(_coerce_text(result.get("answer") or result.get("content")), 900)
            if not text:
                return None, None, latency_ms
            citations = normalize_kb_citations(result.get("citations") or [])
            if text and not citations:
                citations = [
                    {
                        "source_type": "kb",
                        "title": _trim_sentence(f"{kb_name} knowledge base retrieval", 120),
                        "kb_name": kb_name,
                        "doc_name": kb_name,
                        "page_start": None,
                        "page_end": None,
                        "section_path": "",
                        "chunk_id": "",
                        "snippet": _trim_sentence(text, 220),
                    }
                ]
            return (
                {
                    "kb_name": kb_name,
                    "answer": text,
                    "provider": _coerce_text(result.get("provider")) or "unknown",
                    "mode": _coerce_text(result.get("mode")) or search_mode,
                    "retrieval_profile": retrieval_profile,
                    "citations": citations,
                },
                None,
                latency_ms,
            )
        except Exception as exc:
            return None, f"KB search failed ({kb_name}): {exc}", 0

    async def run(
        self,
        *,
        title: str,
        language: str,
        source_text: str,
        instructions: str,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        enable_kb = _as_bool(
            settings.get("enable_kb_research"),
            default=_as_bool(settings.get("use_kb"), default=False),
        )
        enable_search = _as_bool(
            settings.get("enable_web_search"),
            default=_as_bool(settings.get("use_search"), default=False),
        )
        raw_kb_names = self._normalize_kb_names(settings)
        search_effort = self._normalize_effort(settings.get("search_effort"))
        search_provider = (
            _coerce_text(settings.get("search_provider")).lower() or self._default_search_provider()
        )

        sparse = self._source_is_sparse(source_text)
        queries = self._build_queries(
            title=title,
            source_text=source_text,
            instructions=instructions,
            language=language,
            effort=search_effort,
        )
        query = queries[0] if queries else self._build_query(title, source_text, instructions, language)

        enriched_chunks: list[str] = []
        content_expansion_chunks: list[str] = []
        warnings: list[str] = []
        research_notes: list[str] = []
        evidence_catalog: list[dict[str, Any]] = []
        used_kb = False
        used_search = False
        used_kb_names: list[str] = []
        kb_names = raw_kb_names
        available_kbs: list[str] = []
        kb_runs: list[dict[str, Any]] = []
        web_run: dict[str, Any] | None = None
        kb_total_latency = 0
        started_total = time.perf_counter()

        if enable_search:
            web_payloads: list[tuple[str, dict[str, Any]]] = []
            web_warnings: list[str] = []
            for web_query in queries or [query]:
                web_payload, web_warning = self._search_web(
                    query=web_query,
                    provider=search_provider,
                    effort=search_effort,
                )
                if web_warning:
                    web_warnings.append(web_warning)
                if web_payload:
                    web_payloads.append((web_query, web_payload))
            warnings.extend(_dedupe_keep_order(web_warnings))

            if web_payloads:
                used_search = True
                provider_used = _coerce_text(web_payloads[0][1].get("provider")) or search_provider
                total_latency = sum(_as_int(item[1].get("latency_ms"), 0) for item in web_payloads)
                merged_answers = [
                    _coerce_text(item[1].get("answer"))
                    for item in web_payloads
                    if _coerce_text(item[1].get("answer"))
                ]
                web_answer = "\n\n".join(_dedupe_keep_order(merged_answers)[:3])
                merged_citations: list[dict[str, Any]] = []
                seen_citation_keys: set[str] = set()
                for _, payload in web_payloads:
                    for citation in payload.get("citations") or []:
                        if not isinstance(citation, dict):
                            continue
                        citation_key = "|".join(
                            [
                                _coerce_text(citation.get("url")),
                                _coerce_text(citation.get("title")),
                                _coerce_text(citation.get("snippet")),
                            ]
                        )
                        if citation_key in seen_citation_keys:
                            continue
                        seen_citation_keys.add(citation_key)
                        merged_citations.append(citation)
                web_citations = merged_citations[:12]
                evidence_catalog.extend(web_citations)
                citation_preview = []
                for item in web_citations[:4]:
                    if not isinstance(item, dict):
                        continue
                    entry = _coerce_text(item.get("title") or item.get("snippet") or item.get("url"))
                    if entry:
                        citation_preview.append(_trim_sentence(entry, 180))
                if web_answer:
                    for note in _short_lines(web_answer, limit=5):
                        research_notes.append(_trim_sentence(note, 160))
                    content_expansion_chunks.append(_trim_sentence(web_answer, 900))

                web_run = {
                    "provider": provider_used,
                    "effort": search_effort,
                    "latency_ms": total_latency,
                    "citation_count": len(web_citations),
                    "warning": "",
                    "query_count": len(web_payloads),
                }

                block = [
                    (
                        "### Web research expansion "
                        f"({provider_used}, effort: {search_effort}, queries: {len(web_payloads)})"
                    )
                ]
                for idx, (web_query, payload) in enumerate(web_payloads[:3], start=1):
                    answer = _coerce_text(payload.get("answer"))
                    if not answer:
                        continue
                    block.append(f"Q{idx}: {_trim_sentence(web_query, 160)}")
                    block.append(_trim_sentence(answer, 400))
                if citation_preview:
                    block.append("")
                    block.append("Sources:")
                    block.extend([f"- {item}" for item in citation_preview[:4]])
                enriched_chunks.append("\n".join(block))

        if enable_kb:
            available_kbs, listing_warning = self._available_kb_names()
            if listing_warning:
                warnings.append(listing_warning)
            if available_kbs:
                invalid = [name for name in kb_names if name not in available_kbs]
                if invalid:
                    warnings.append(
                        f"Some selected KBs are unavailable and were skipped: {', '.join(invalid)}"
                    )
                kb_names = [name for name in kb_names if name in available_kbs]
                if not kb_names:
                    default_kb = self._default_kb_name(available_kbs)
                    if default_kb:
                        kb_names = [default_kb]
            elif kb_names:
                warnings.append("Knowledge base listing failed; selected KB retrieval was skipped.")

            kb_queries = (queries or [query])[: (2 if search_effort == "high" else 1)]
            kb_tasks: list[Any] = []
            kb_task_meta: list[dict[str, str]] = []
            for kb_name in kb_names:
                runtime_cfg = self._kb_runtime_config(kb_name)
                for kb_query in kb_queries:
                    kb_task_meta.append(
                        {
                            "kb_name": kb_name,
                            "query": kb_query,
                            "search_mode": runtime_cfg["search_mode"],
                            "retrieval_profile": runtime_cfg["retrieval_profile"],
                            "rag_provider": runtime_cfg["rag_provider"],
                        }
                    )
                    kb_tasks.append(
                        self._search_kb(
                            kb_query,
                            kb_name,
                            search_mode=runtime_cfg["search_mode"],
                            retrieval_profile=runtime_cfg["retrieval_profile"],
                        )
                    )
            if kb_tasks:
                results = await asyncio.gather(*kb_tasks, return_exceptions=False)
                for idx, (payload, kb_warning, latency_ms) in enumerate(results):
                    meta = kb_task_meta[idx]
                    kb_total_latency += latency_ms
                    run_item = {
                        "kb_name": meta["kb_name"],
                        "query": _trim_sentence(meta.get("query"), 140),
                        "provider": meta["rag_provider"],
                        "mode": meta["search_mode"],
                        "retrieval_profile": meta["retrieval_profile"],
                        "latency_ms": latency_ms,
                        "citation_count": 0,
                        "warning": kb_warning or "",
                    }
                    if kb_warning:
                        warnings.append(kb_warning)
                    if payload:
                        used_kb = True
                        used_kb_names.append(meta["kb_name"])
                        kb_citations = payload.get("citations") or []
                        run_item["citation_count"] = len(kb_citations)
                        evidence_catalog.extend(kb_citations)
                        citation_preview = []
                        for item in kb_citations[:3]:
                            if not isinstance(item, dict):
                                continue
                            preview = _coerce_text(item.get("title") or item.get("doc_name"))
                            if preview:
                                citation_preview.append(preview)
                        enriched_chunks.append(
                            "\n".join(
                                [
                                    (
                                        "### Knowledge base expansion "
                                        f"- {meta['kb_name']} "
                                        f"({payload.get('provider')} | mode: {payload.get('mode')} "
                                        f"| profile: {meta['retrieval_profile']})"
                                    ),
                                    f"Query: {_trim_sentence(meta.get('query'), 160)}",
                                    payload.get("answer", ""),
                                    "Sources:" if citation_preview else "",
                                    *([f"- {item}" for item in citation_preview] if citation_preview else []),
                                ]
                            )
                        )
                        kb_answer = _trim_sentence(_coerce_text(payload.get("answer")), 900)
                        if kb_answer:
                            content_expansion_chunks.append(kb_answer)
                        research_notes.append(_trim_sentence(payload.get("answer", ""), 160))
                    kb_runs.append(run_item)
            elif enable_kb:
                warnings.append("Knowledge base retrieval enabled but no usable KB was selected.")

        expanded_source = source_text.strip()
        if content_expansion_chunks:
            enrich_text = "\n\n".join(_dedupe_keep_order(content_expansion_chunks)).strip()
            expanded_source = (
                f"{expanded_source}\n\n{enrich_text}" if expanded_source else enrich_text
            )

        if (enable_kb or enable_search) and not (used_kb or used_search):
            warnings.append("Research agent was enabled but produced no external retrieval context.")
        elif sparse and not enriched_chunks:
            warnings.append(
                "Source material is sparse and no external expansion was applied. Result may be generic."
            )

        deduped_evidence: list[dict[str, Any]] = []
        seen_evidence: set[str] = set()
        for item in evidence_catalog:
            if not isinstance(item, dict):
                continue
            key = "|".join(
                [
                    _coerce_text(item.get("source_type")),
                    _coerce_text(item.get("url")),
                    _coerce_text(item.get("kb_name")),
                    _coerce_text(item.get("doc_name")),
                    _coerce_text(item.get("chunk_id")),
                    _coerce_text(item.get("title")),
                ]
            )
            if key in seen_evidence:
                continue
            seen_evidence.add(key)
            deduped_evidence.append(item)

        latencies = {
            "web": _as_int((web_run or {}).get("latency_ms"), 0),
            "kb_total": kb_total_latency,
            "total": int((time.perf_counter() - started_total) * 1000),
        }
        deduped_warnings = _dedupe_keep_order(warnings)
        research_trace = {
            "enabled_kb": enable_kb,
            "enabled_search": enable_search,
            "queries": queries,
            "kb_runs": kb_runs,
            "web_run": web_run,
            "latencies_ms": latencies,
            "warnings": deduped_warnings,
        }

        return {
            "source_text": expanded_source,
            "source_was_sparse": sparse,
            "used_kb": used_kb,
            "used_search": used_search,
            "kb_enabled": enable_kb,
            "search_enabled": enable_search,
            "kb_names": kb_names,
            "used_kb_names": used_kb_names,
            "available_kb_names": available_kbs,
            "search_provider": search_provider,
            "search_effort": search_effort,
            "query": query,
            "queries": queries,
            "research_notes": research_notes[:6],
            "warnings": deduped_warnings,
            "evidence_catalog": deduped_evidence,
            "research_trace": research_trace,
        }


class SlideContentAgent:
    _point_labels = ("Claim", "Evidence", "Implication")

    @staticmethod
    def _normalize_slide_payload(slide: dict[str, Any], index: int) -> dict[str, Any]:
        title = _trim_sentence(_coerce_text(slide.get("title")) or f"Slide {index}", 88)
        objective = _trim_sentence(
            _coerce_text(slide.get("objective")) or "Explain the core message clearly.",
            170,
        )
        key_points = _normalize_key_points(
            slide.get("key_points") or [],
            max_items=5,
            fallback_subject=objective or title,
        )
        speaker_notes = _trim_sentence(
            _coerce_text(slide.get("speaker_notes")) or objective,
            220,
        )
        asset_focus = _trim_sentence(
            _coerce_text(slide.get("asset_focus")) or objective,
            140,
        )
        evidence_refs = [
            _coerce_text(item)
            for item in (slide.get("evidence_refs") or [])
            if _coerce_text(item)
        ]
        return {
            "title": title,
            "objective": objective,
            "key_points": key_points,
            "speaker_notes": speaker_notes,
            "asset_focus": asset_focus,
            "evidence_refs": evidence_refs[:5],
        }

    @staticmethod
    def _is_placeholder_line(line: str) -> bool:
        normalized = _coerce_text(line).lower()
        normalized_compact = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
        placeholder_tokens = {
            "context",
            "action",
            "metric",
            "metrics",
            "insight",
            "insights",
            "details",
            "data",
            "content",
            "todo",
            "tbd",
            "key idea",
            "supporting evidence",
            "actionable takeaway",
            "core point",
            "evidence",
            "takeaway",
            "explain the core message clearly",
        }
        if not normalized:
            return True
        if normalized in placeholder_tokens or normalized_compact in placeholder_tokens:
            return True
        if "explain the core message clearly" in normalized_compact:
            return True
        if "knowledge base expansion" in normalized_compact:
            return True
        if "web research expansion" in normalized_compact:
            return True
        pattern_hits = [
            r"^slide\s+\d+$",
            r"^part\s+\d+$",
            r"^alternative perspective\b",
            r"^\(?new angle\)?$",
        ]
        return any(re.match(pattern, normalized_compact) for pattern in pattern_hits)

    @staticmethod
    def _hint_sentences(chunk_hint: str) -> list[str]:
        parts = [
            _trim_sentence(segment.strip(), 140)
            for segment in re.split(r"[.;:\n]+", chunk_hint or "")
            if segment.strip()
        ]
        output: list[str] = []
        for item in parts:
            if not item or SlideContentAgent._is_placeholder_line(item):
                continue
            output.append(item)
        return output

    @staticmethod
    def _fallback_objective(
        *,
        index: int,
        deck_title: str,
        chunk_hint: str,
    ) -> str:
        hints = SlideContentAgent._hint_sentences(chunk_hint)
        if hints:
            return _trim_sentence(hints[0], 160)
        title_seed = _trim_sentence(deck_title or "the topic", 60)
        return _trim_sentence(
            f"Explain the key development in {title_seed} for section {index}.",
            160,
        )

    @staticmethod
    def _sanitize_slide_payload(
        *,
        slide: dict[str, Any],
        index: int,
        chunk_hint: str,
        deck_title: str,
    ) -> dict[str, Any]:
        normalized = SlideContentAgent._normalize_slide_payload(slide, index)
        objective = _trim_sentence(_coerce_text(normalized.get("objective")), 160)
        if SlideContentAgent._is_placeholder_line(objective):
            objective = SlideContentAgent._fallback_objective(
                index=index,
                deck_title=deck_title,
                chunk_hint=chunk_hint,
            )
        normalized["objective"] = objective

        title = _trim_sentence(_coerce_text(normalized.get("title")), 88)
        if SlideContentAgent._is_placeholder_line(title):
            title = _trim_sentence(
                f"{deck_title or 'Slide deck'} - Part {index}",
                88,
            )
        normalized["title"] = title

        points = _normalize_key_points(
            normalized.get("key_points") or [],
            max_items=5,
            fallback_subject=objective or title,
        )
        safe_points: list[str] = []
        hint_items = SlideContentAgent._hint_sentences(chunk_hint)
        for point in points:
            text = _trim_sentence(_coerce_text(point), 140)
            if SlideContentAgent._is_placeholder_line(text):
                continue
            if text not in safe_points:
                safe_points.append(text)
            if len(safe_points) >= 5:
                break
        hint_idx = 0
        while len(safe_points) < 3 and hint_idx < len(hint_items):
            hint = hint_items[hint_idx]
            hint_idx += 1
            if hint and hint not in safe_points:
                safe_points.append(hint)
        while len(safe_points) < 3:
            candidate = _trim_sentence(
                f"Evidence-backed implication for {deck_title or 'this topic'} ({len(safe_points) + 1}).",
                140,
            )
            if candidate not in safe_points:
                safe_points.append(candidate)

        structured_points: list[str] = []
        for point_index, point in enumerate(safe_points[:5]):
            text = _trim_sentence(_coerce_text(point), 124)
            if not text:
                continue
            if point_index < len(SlideContentAgent._point_labels):
                label = SlideContentAgent._point_labels[point_index]
                if not text.lower().startswith(f"{label.lower()}:"):
                    text = f"{label}: {text}"
            structured_points.append(_trim_sentence(text, 140))
        normalized["key_points"] = structured_points[:5]

        speaker_notes = _trim_sentence(_coerce_text(normalized.get("speaker_notes")), 220)
        if SlideContentAgent._is_placeholder_line(speaker_notes):
            speaker_notes = objective
        normalized["speaker_notes"] = speaker_notes

        asset_focus = _trim_sentence(_coerce_text(normalized.get("asset_focus")), 140)
        if SlideContentAgent._is_placeholder_line(asset_focus):
            asset_focus = objective
        normalized["asset_focus"] = asset_focus
        return normalized

    @staticmethod
    def _source_chunk_allocator(source_text: str, count: int) -> list[str]:
        raw_lines = [line.strip() for line in source_text.splitlines() if line.strip()]
        lines = [
            line
            for line in raw_lines
            if len(line) > 8 and not SlideContentAgent._is_noise_source_line(line)
        ]
        if not lines:
            lines = [
                line
                for line in _short_lines(source_text, limit=max(8, count * 2))
                if not SlideContentAgent._is_noise_source_line(line)
            ]
        if not lines:
            lines = [f"Core idea {idx + 1}" for idx in range(max(1, count))]

        chunk_size = max(1, len(lines) // max(1, count))
        chunks: list[str] = []
        cursor = 0
        for _ in range(count):
            chunk_lines = lines[cursor : cursor + chunk_size]
            if not chunk_lines:
                chunk_lines = [lines[min(len(lines) - 1, cursor % len(lines))]]
            chunks.append(_trim_sentence(" ".join(chunk_lines), 320))
            cursor += chunk_size
        return chunks

    @staticmethod
    def _is_noise_source_line(line: str) -> bool:
        text = _coerce_text(line).strip()
        if not text:
            return True
        compact = text.lower()
        if compact.startswith("###") or compact.startswith("sources:"):
            return True
        if compact.startswith("- ") and ("http" in compact or "kb" in compact or "source" in compact):
            return True
        if re.match(r"^\[s\d+\]\s*", compact):
            return True
        if compact.startswith("query:"):
            return True
        if "knowledge base expansion" in compact or "web research expansion" in compact:
            return True
        if compact.startswith("http://") or compact.startswith("https://"):
            return True
        return False

    @staticmethod
    def _evidence_snippets(research_context: dict[str, Any], limit: int = 12) -> list[str]:
        snippets: list[str] = []
        catalog = research_context.get("evidence_catalog") if isinstance(research_context, dict) else []
        if not isinstance(catalog, list):
            return snippets
        for item in catalog:
            if not isinstance(item, dict):
                continue
            citation_id = _coerce_text(item.get("id"))
            raw_text = _coerce_text(item.get("snippet") or item.get("title") or item.get("short_ref"))
            if not raw_text:
                continue
            clean = _trim_sentence(re.sub(r"\s+", " ", raw_text), 180)
            prefix = f"[{citation_id}] " if citation_id else ""
            line = _trim_sentence(f"{prefix}{clean}", 190)
            if line and line not in snippets:
                snippets.append(line)
            if len(snippets) >= limit:
                break
        return snippets

    @staticmethod
    def _inject_evidence_into_slides(slides: list[dict[str, Any]], evidence_snippets: list[str]) -> list[dict[str, Any]]:
        if not evidence_snippets:
            return slides
        output: list[dict[str, Any]] = []
        for idx, slide in enumerate(slides):
            if not isinstance(slide, dict):
                continue
            next_slide = dict(slide)
            objective = _coerce_text(next_slide.get("objective"))
            objective = objective.replace("Highlight a distinct angle for this slide.", "").strip()
            next_slide["objective"] = _trim_sentence(objective, 160)

            points = _normalize_key_points(next_slide.get("key_points") or [], max_items=5, fallback_subject=objective)
            evidence_index = min(len(evidence_snippets) - 1, idx % len(evidence_snippets))
            evidence_line = evidence_snippets[evidence_index]
            evidence_line = re.sub(r"^\[[^\]]+\]\s*", "", evidence_line).strip()
            if SlideContentAgent._is_noise_source_line(evidence_line):
                evidence_line = "Source-backed finding from retrieved evidence."
            if len(points) < 3:
                while len(points) < 3:
                    points.append("Key supporting point")

            # Force the second bullet to carry an explicit source-backed evidence line.
            points[1] = _trim_sentence(
                f"Evidence: {evidence_line}",
                140,
            )
            points[0] = points[0] if points[0].lower().startswith("claim:") else f"Claim: {points[0]}"
            points[2] = points[2] if points[2].lower().startswith("implication:") else f"Implication: {points[2]}"
            next_slide["key_points"] = [_trim_sentence(point, 140) for point in points[:5]]
            output.append(next_slide)
        return output

    @staticmethod
    def _normalize_with_chunk_hint(
        slide: dict[str, Any],
        index: int,
        chunk_hint: str,
        deck_title: str,
    ) -> dict[str, Any]:
        normalized = SlideContentAgent._normalize_slide_payload(slide, index)
        key_points = normalized.get("key_points", [])
        if not isinstance(key_points, list):
            key_points = []

        safe_points: list[str] = []
        hint_parts = [part.strip() for part in re.split(r"[.;:\n]+", chunk_hint) if part.strip()]
        for idx, point in enumerate(key_points):
            text = _trim_sentence(_coerce_text(point), 140)
            if SlideContentAgent._is_placeholder_line(text):
                fallback = hint_parts[idx] if idx < len(hint_parts) else chunk_hint
                text = _trim_sentence(fallback or normalized.get("objective", "Key point"), 140)
            safe_points.append(text)
        while len(safe_points) < 3:
            filler = hint_parts[len(safe_points)] if len(hint_parts) > len(safe_points) else normalized.get("objective")
            safe_points.append(_trim_sentence(_coerce_text(filler) or "Key supporting point.", 140))
        normalized["key_points"] = safe_points[:5]

        objective = _coerce_text(normalized.get("objective"))
        if SlideContentAgent._is_placeholder_line(objective):
            normalized["objective"] = _trim_sentence(chunk_hint or f"Explain slide {index}.", 160)
        return SlideContentAgent._sanitize_slide_payload(
            slide=normalized,
            index=index,
            chunk_hint=chunk_hint,
            deck_title=deck_title,
        )

    async def _llm_outline(
        self,
        *,
        title: str,
        language: str,
        count: int,
        style: str,
        instructions: str,
        source_text: str,
        model: str | None,
    ) -> list[dict[str, Any]]:
        system_prompt = (
            "You are the Outline Agent. Return strict JSON object with key 'slides'. "
            "Each slide needs title, objective, asset_focus. "
            "Must return EXACT requested number of slides and no placeholders."
        )
        prompt = (
            f"Language: {language}\n"
            f"Deck title: {title or 'Untitled deck'}\n"
            f"Requested slide count: {count}\n"
            f"Template: {style}\n"
            f"Instructions: {instructions}\n"
            "Source excerpt:\n"
            f"{source_text[:7000]}"
        )
        response = await complete(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            temperature=0.2,
            max_tokens=1800,
        )
        parsed = parse_json_response(response, fallback={})
        slides = parsed.get("slides", []) if isinstance(parsed, dict) else []
        return [item for item in slides if isinstance(item, dict)]

    async def _llm_slides_from_outline(
        self,
        *,
        outline: list[dict[str, Any]],
        count: int,
        language: str,
        style: str,
        instructions: str,
        source_text: str,
        research_notes: list[str],
        evidence_snippets: list[str],
        model: str | None,
    ) -> dict[str, Any]:
        system_prompt = (
            "You are the Content Agent for slide generation. Return strict JSON with keys "
            "learning_goals (string[]) and slides (array). "
            "Each slide must include title, objective, key_points (3-5), speaker_notes, asset_focus. "
            "Do not emit placeholder bullets like Context/Action/Metric. "
            "Key points must start with Claim:, Evidence:, Implication: for the first three bullets. "
            "Avoid generic filler phrases. Avoid using page numbers or lecture indices as pseudo-statistics."
        )
        prompt = (
            f"Language: {language}\n"
            f"Template style: {style}\n"
            f"Requested slides: {count}\n"
            f"Instructions: {instructions}\n"
            f"Research notes: {json.dumps(research_notes[:8], ensure_ascii=False)}\n"
            f"Evidence snippets: {json.dumps(evidence_snippets[:10], ensure_ascii=False)}\n"
            f"Outline: {json.dumps(outline[:count], ensure_ascii=False)}\n"
            "Source text:\n"
            f"{source_text[:9000]}"
        )
        response = await complete(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            temperature=0.25,
            max_tokens=3200,
        )
        parsed = parse_json_response(response, fallback={})
        return parsed if isinstance(parsed, dict) else {}

    async def run(
        self,
        *,
        title: str,
        language: str,
        source_text: str,
        instructions: str,
        settings: dict[str, Any],
        research_context: dict[str, Any],
    ) -> dict[str, Any]:
        count = _slide_count(settings)
        model = _preferred_pro_model()
        style = _template_id(settings)
        style_guide = TEMPLATE_STYLE_GUIDES.get(style, TEMPLATE_STYLE_GUIDES["academic_evidence"])
        allocated_chunks = self._source_chunk_allocator(source_text, count)
        evidence_snippets = self._evidence_snippets(research_context, limit=12)

        try:
            outline = await self._llm_outline(
                title=title,
                language=language,
                count=count,
                style=style,
                instructions=instructions,
                source_text=source_text,
                model=model,
            )
            if len(outline) < count:
                for idx in range(len(outline), count):
                    outline.append(
                        {
                            "title": _trim_sentence(f"{title or 'Deck'} - Part {idx + 1}", 88),
                            "objective": _trim_sentence(allocated_chunks[idx], 160),
                            "asset_focus": _trim_sentence(allocated_chunks[idx], 140),
                        }
                    )

            parsed = await self._llm_slides_from_outline(
                outline=outline,
                count=count,
                language=language,
                style=style,
                instructions=instructions,
                source_text=source_text,
                research_notes=research_context.get("research_notes", []),
                evidence_snippets=evidence_snippets,
                model=model,
            )

            goals = parsed.get("learning_goals", []) if isinstance(parsed, dict) else []
            raw_slides = parsed.get("slides", []) if isinstance(parsed, dict) else []
            normalized: list[dict[str, Any]] = []
            if isinstance(raw_slides, list):
                for idx, slide in enumerate(raw_slides[:count], start=1):
                    if isinstance(slide, dict):
                        normalized.append(
                            self._normalize_with_chunk_hint(
                                slide,
                                idx,
                                allocated_chunks[idx - 1],
                                title,
                            )
                        )

            continuation_attempt = 0
            while len(normalized) < count and continuation_attempt < 2:
                remaining = count - len(normalized)
                continuation_attempt += 1
                continuation_prompt = (
                    "Continue slide generation in strict JSON with key 'slides'. "
                    f"Generate EXACT {remaining} additional slides. "
                    "Avoid placeholders and duplicate titles.\n"
                    f"Existing titles: {json.dumps([item.get('title') for item in normalized], ensure_ascii=False)}\n"
                    f"Outline (remaining): {json.dumps(outline[len(normalized):count], ensure_ascii=False)}\n"
                    f"Source hints: {json.dumps(allocated_chunks[len(normalized):count], ensure_ascii=False)}"
                )
                continuation = await complete(
                    prompt=continuation_prompt,
                    system_prompt="You are a continuation content generator for presentation slides.",
                    model=model,
                    temperature=0.2,
                    max_tokens=1800,
                )
                continuation_parsed = parse_json_response(continuation, fallback={})
                continuation_slides = (
                    continuation_parsed.get("slides", [])
                    if isinstance(continuation_parsed, dict)
                    else []
                )
                if not isinstance(continuation_slides, list) or not continuation_slides:
                    break
                for slide in continuation_slides:
                    if not isinstance(slide, dict):
                        continue
                    idx = len(normalized) + 1
                    normalized.append(
                        self._normalize_with_chunk_hint(
                            slide,
                            idx,
                            allocated_chunks[idx - 1],
                            title,
                        )
                    )
                    if len(normalized) >= count:
                        break

            while len(normalized) < count:
                idx = len(normalized) + 1
                line = allocated_chunks[idx - 1]
                normalized.append(
                    {
                        "title": f"{title or 'Slide Deck'} - Part {idx}",
                        "objective": _trim_sentence(line, 160),
                        "key_points": _normalize_key_points(
                            [line, f"Impact of {line}", f"Practical implication of {line}"],
                            max_items=4,
                            fallback_subject=line,
                        ),
                        "speaker_notes": _trim_sentence(line, 190),
                        "asset_focus": _trim_sentence(line, 140),
                        "evidence_refs": [],
                    }
                )

            normalized = [
                self._sanitize_slide_payload(
                    slide=slide,
                    index=idx + 1,
                    chunk_hint=allocated_chunks[idx] if idx < len(allocated_chunks) else "",
                    deck_title=title,
                )
                for idx, slide in enumerate(normalized[:count])
            ]
            normalized = self._inject_evidence_into_slides(normalized, evidence_snippets)

            if normalized:
                return {
                    "learning_goals": [
                        _trim_sentence(_coerce_text(goal), 120)
                        for goal in goals
                        if _coerce_text(goal)
                    ][:6]
                    or [
                        f"Understand the {style_guide.get('tone', 'core')} storyline.",
                        "Interpret evidence and limitations.",
                        "Translate findings into actionable next steps.",
                    ],
                    "slides": normalized[:count],
                    "source": "llm",
                }
        except Exception as exc:
            logger.warning(f"Content agent LLM fallback engaged: {exc}")

        fallback_lines = self._source_chunk_allocator(source_text or instructions or title, count)
        slides: list[dict[str, Any]] = []
        for idx in range(count):
            line = fallback_lines[idx] if idx < len(fallback_lines) else f"Core idea {idx + 1}"
            slides.append(
                {
                    "title": f"{title or 'Slide Deck'} - Part {idx + 1}",
                    "objective": _trim_sentence(line, 160),
                    "key_points": _normalize_key_points(
                        [line, f"Why {line} matters", f"How to apply {line}", "Expected impact"],
                        max_items=4,
                        fallback_subject=line,
                    ),
                    "speaker_notes": _trim_sentence(line, 180),
                    "asset_focus": _trim_sentence(line, 120),
                    "evidence_refs": [],
                }
            )
        slides = [
            self._sanitize_slide_payload(
                slide=slide,
                index=idx + 1,
                chunk_hint=fallback_lines[idx] if idx < len(fallback_lines) else "",
                deck_title=title,
            )
            for idx, slide in enumerate(slides)
        ]
        return {
            "learning_goals": [
                "Understand the key storyline.",
                "Interpret supporting evidence.",
                "Apply insights to concrete actions.",
            ],
            "slides": slides,
            "source": "fallback",
        }

    def revise_slide(self, slide: dict[str, Any], reasons: list[str], attempt: int) -> dict[str, Any]:
        revised = dict(slide)
        objective = _coerce_text(revised.get("objective")) or "Clarify the key message."
        points = _normalize_key_points(
            revised.get("key_points") or [],
            max_items=5,
            fallback_subject=objective,
        )
        title = _coerce_text(revised.get("title")) or "Slide"
        asset_focus = _coerce_text(revised.get("asset_focus")) or objective

        reasons_joined = " ".join(reasons).lower()
        if any(
            token in reasons_joined
            for token in ["content_density", "readability", "overflow", "layout_overlap", "contrast"]
        ):
            point_cap = max(3, 5 - min(2, attempt))
            points = [_trim_sentence(point, max(54, 88 - attempt * 10)) for point in points[:point_cap]]
            objective = _trim_sentence(objective, max(92, 140 - attempt * 14))

        if "layout_repetition" in reasons_joined:
            title = _trim_sentence(title, 72)
            objective = _trim_sentence(objective, 150)

        if "missing_citation" in reasons_joined and len(points) >= 2:
            points[1] = _trim_sentence(
                "Evidence: Attach a concrete source-backed fact with explicit citation marker.",
                132,
            )

        if "duplicate_asset" in reasons_joined or "missing_asset" in reasons_joined:
            asset_focus = _trim_sentence(f"{asset_focus} variation {attempt + 1}", 130)

        revised["title"] = title
        revised["objective"] = objective
        revised["key_points"] = points or ["Core point", "Evidence", "Takeaway"]
        revised["speaker_notes"] = _trim_sentence(
            _coerce_text(revised.get("speaker_notes")) or objective,
            210,
        )
        revised["asset_focus"] = asset_focus
        return self._sanitize_slide_payload(
            slide=revised,
            index=max(1, _as_int(_coerce_text(revised.get("id")).lstrip("s"), 1)),
            chunk_hint=_coerce_text(revised.get("objective")) or objective,
            deck_title=_coerce_text(revised.get("title")) or title,
        )


class SlideLayoutAgent:
    @staticmethod
    def _pool(template_id: str) -> list[str]:
        pool = TEMPLATE_LAYOUT_POOLS.get(template_id)
        if pool:
            return [item for item in pool if item in _layout_map()]
        return [item["id"] for item in LAYOUT_VARIANTS]

    @staticmethod
    def _asset_specs(
        slide_payload: dict[str, Any],
        layout_spec: dict[str, Any],
        template_id: str,
        index: int,
        attempt: int = 0,
    ) -> list[dict[str, Any]]:
        style_guide = TEMPLATE_STYLE_GUIDES.get(
            template_id, TEMPLATE_STYLE_GUIDES["academic_evidence"]
        )
        title = _coerce_text(slide_payload.get("title")) or f"Slide {index + 1}"
        objective = _coerce_text(slide_payload.get("objective")) or "Explain key point."
        asset_focus = _coerce_text(slide_payload.get("asset_focus")) or objective
        chart_type = _coerce_text(layout_spec.get("chart_type")) or "bar"
        specs = [
            {
                "id": f"a_img_{index+1}",
                "type": "image",
                "description": f"Primary visual for slide {index + 1}",
                "prompt": _trim_sentence(
                    f"{title} | {asset_focus} | style: {style_guide.get('asset_voice')}",
                    180,
                ),
            },
            {
                "id": f"a_chart_{index+1}",
                "type": "chart",
                "description": f"Quant chart for slide {index + 1}",
                "prompt": _trim_sentence(f"{title} metrics from key points", 150),
                "chart_type": chart_type,
            },
        ]
        if layout_spec.get("metric_cards", 0) > 0:
            specs.append(
                {
                    "id": f"a_icon_{index+1}",
                    "type": "icon",
                    "description": f"Supporting icon set for slide {index + 1}",
                    "prompt": _trim_sentence(f"{title} symbolized in minimal icon language", 140),
                }
            )
        if attempt > 0:
            for spec in specs:
                spec["prompt"] = _trim_sentence(f"{spec['prompt']} | retry {attempt}", 190)
        return specs

    @staticmethod
    def _enforce_slot_guards(slots: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
        guarded = json.loads(json.dumps(slots))
        title_box = guarded.get("title")
        objective_box = guarded.get("objective")
        chart_box = guarded.get("chart")
        callout_box = guarded.get("callout")
        bullets_box = guarded.get("bullets")
        min_chart_h = int(_clamp(_as_int(constraints.get("min_chart_h"), 180), 120, 360))
        max_bullets = int(_clamp(_as_int(constraints.get("max_bullets"), 4), 1, 6))

        if isinstance(title_box, dict):
            title_box["h"] = int(_clamp(_as_int(title_box.get("h"), 110), 72, 180))
            title_box["y"] = int(_clamp(_as_int(title_box.get("y"), 56), 16, CANVAS_HEIGHT - title_box["h"] - 16))
            guarded["title"] = title_box

        if isinstance(objective_box, dict):
            objective_box["h"] = int(_clamp(_as_int(objective_box.get("h"), 70), 52, 130))
            objective_min_y = 16
            if isinstance(title_box, dict):
                objective_min_y = _as_int(title_box.get("y"), 16) + _as_int(title_box.get("h"), 100) + 10
            objective_max_y = CANVAS_HEIGHT - objective_box["h"] - 16
            objective_min_y = int(min(objective_min_y, objective_max_y))
            objective_box["y"] = int(
                _clamp(
                    _as_int(objective_box.get("y"), objective_min_y),
                    objective_min_y,
                    objective_max_y,
                )
            )
            guarded["objective"] = objective_box

        if isinstance(chart_box, dict):
            chart_box["h"] = int(_clamp(_as_int(chart_box.get("h"), min_chart_h), min_chart_h, 360))
            chart_max_y = CANVAS_HEIGHT - chart_box["h"] - 16
            chart_box["y"] = int(_clamp(_as_int(chart_box.get("y"), 16), 16, chart_max_y))
            if isinstance(objective_box, dict):
                min_chart_y = _as_int(objective_box.get("y"), 0) + _as_int(objective_box.get("h"), 0) + 14
                min_chart_y = int(min(min_chart_y, chart_max_y))
                chart_box["y"] = int(
                    _clamp(
                        _as_int(chart_box.get("y"), min_chart_y),
                        min_chart_y,
                        chart_max_y,
                    )
                )
            guarded["chart"] = chart_box

        if isinstance(callout_box, dict):
            callout_box["h"] = int(_clamp(_as_int(callout_box.get("h"), 96), 48, 220))
            callout_box["y"] = int(_clamp(_as_int(callout_box.get("y"), 520), 16, CANVAS_HEIGHT - callout_box["h"] - 16))
            blockers: list[dict[str, Any]] = []
            for key in ("chart", "image", "bullets", "objective", "title"):
                box = guarded.get(key)
                if isinstance(box, dict):
                    blockers.append(box)
            for blocker in blockers:
                if not _boxes_overlap(callout_box, blocker):
                    continue
                blocker_y = _as_int(blocker.get("y"), 0)
                blocker_h = _as_int(blocker.get("h"), 0)
                preferred_y = blocker_y - callout_box["h"] - 12
                if preferred_y >= 16:
                    callout_box["y"] = preferred_y
                else:
                    callout_box["y"] = int(
                        _clamp(
                            blocker_y + blocker_h + 12,
                            16,
                            CANVAS_HEIGHT - callout_box["h"] - 16,
                        )
                    )
                if _boxes_overlap(callout_box, blocker):
                    available_h = blocker_y - _as_int(callout_box.get("y"), 16) - 12
                    if available_h > 48:
                        callout_box["h"] = int(_clamp(available_h, 48, 220))
            for anchor_key in ("title", "objective"):
                anchor = guarded.get(anchor_key)
                if not isinstance(anchor, dict):
                    continue
                if not _boxes_overlap(callout_box, anchor):
                    continue
                anchor_bottom = _as_int(anchor.get("y"), 0) + _as_int(anchor.get("h"), 0) + 12
                max_callout_y = CANVAS_HEIGHT - _as_int(callout_box.get("h"), 80) - 16
                callout_box["y"] = int(_clamp(anchor_bottom, 16, max_callout_y))
                if _boxes_overlap(callout_box, anchor):
                    reduced_h = CANVAS_HEIGHT - _as_int(callout_box.get("y"), 16) - 16
                    callout_box["h"] = int(_clamp(reduced_h, 48, 220))
            guarded["callout"] = callout_box

        if isinstance(bullets_box, dict):
            min_bullet_h = int(_clamp((max_bullets * 56) + 26, 96, 420))
            bullets_box["h"] = int(_clamp(_as_int(bullets_box.get("h"), min_bullet_h), min_bullet_h, 420))
            bullets_min_y = 16
            if isinstance(objective_box, dict):
                bullets_min_y = _as_int(objective_box.get("y"), 0) + _as_int(objective_box.get("h"), 0) + 12
            bullets_max_y = CANVAS_HEIGHT - bullets_box["h"] - 16
            bullets_min_y = int(min(bullets_min_y, bullets_max_y))
            bullets_box["y"] = int(
                _clamp(
                    _as_int(bullets_box.get("y"), bullets_min_y),
                    bullets_min_y,
                    bullets_max_y,
                )
            )
            bullets_box["w"] = int(_clamp(_as_int(bullets_box.get("w"), 760), 220, CANVAS_WIDTH - _as_int(bullets_box.get("x"), 16) - 16))
            for key in ("image", "chart", "chart_secondary"):
                other_box = guarded.get(key)
                if not isinstance(other_box, dict):
                    continue
                if not _boxes_overlap(bullets_box, other_box):
                    continue
                other_h = _as_int(other_box.get("h"), 200)
                other_x = _as_int(other_box.get("x"), 0)
                bullets_x = _as_int(bullets_box.get("x"), 0)
                # Prefer side-by-side split when boxes share row and there is room.
                if other_x > bullets_x + 260:
                    proposed_w = other_x - bullets_x - 14
                    if proposed_w >= 220:
                        bullets_box["w"] = int(_clamp(proposed_w, 220, bullets_box["w"]))
                if _boxes_overlap(bullets_box, other_box):
                    desired_other_y = _as_int(bullets_box.get("y"), 0) + _as_int(bullets_box.get("h"), 0) + 14
                    max_other_y = CANVAS_HEIGHT - other_h - 16
                    if desired_other_y <= max_other_y:
                        other_box["y"] = desired_other_y
                    else:
                        available_h = _as_int(other_box.get("y"), CANVAS_HEIGHT - 16) - _as_int(bullets_box.get("y"), 0) - 14
                        if available_h >= 96:
                            bullets_box["h"] = int(_clamp(available_h, 96, bullets_box["h"]))
                guarded[key] = other_box
            guarded["bullets"] = bullets_box

        image_box = guarded.get("image")
        chart_box = guarded.get("chart")
        if isinstance(image_box, dict) and isinstance(objective_box, dict) and _boxes_overlap(image_box, objective_box):
            image_h = _as_int(image_box.get("h"), 220)
            image_max_y = CANVAS_HEIGHT - image_h - 16
            objective_bottom = _as_int(objective_box.get("y"), 0) + _as_int(objective_box.get("h"), 0) + 12
            image_box["y"] = int(_clamp(objective_bottom, 16, image_max_y))
            guarded["image"] = image_box
        if isinstance(image_box, dict) and isinstance(chart_box, dict) and _boxes_overlap(image_box, chart_box):
            desired_chart_y = _as_int(image_box.get("y"), 0) + _as_int(image_box.get("h"), 0) + 12
            chart_h = _as_int(chart_box.get("h"), 220)
            chart_max_y = CANVAS_HEIGHT - chart_h - 16
            if desired_chart_y <= chart_max_y:
                chart_box["y"] = desired_chart_y
            else:
                desired_image_y = _as_int(chart_box.get("y"), 0) - _as_int(image_box.get("h"), 220) - 12
                if desired_image_y >= 16:
                    image_box["y"] = desired_image_y
                else:
                    # Last resort: split horizontally if possible.
                    image_x = _as_int(image_box.get("x"), 0)
                    chart_x = _as_int(chart_box.get("x"), 0)
                    if chart_x > image_x + 220:
                        image_box["w"] = int(_clamp(chart_x - image_x - 14, 220, _as_int(image_box.get("w"), 800)))
            guarded["image"] = image_box
            guarded["chart"] = chart_box

        return guarded

    @staticmethod
    def _mutate_slots(base_slots: dict[str, Any], seed: int, constraints: dict[str, Any] | None = None) -> dict[str, Any]:
        slots = json.loads(json.dumps(base_slots))
        keys = sorted([key for key, value in slots.items() if isinstance(value, dict)])
        if not keys:
            return slots

        values = _lcg_values(seed, len(keys) * 4, -1.0, 1.0)
        cursor = 0
        for key in keys:
            box = slots.get(key, {})
            if not isinstance(box, dict):
                continue
            x = _as_int(box.get("x"), 0)
            y = _as_int(box.get("y"), 0)
            w = _as_int(box.get("w"), 100)
            h = _as_int(box.get("h"), 100)
            dx = values[cursor]
            dy = values[cursor + 1]
            dw = values[cursor + 2]
            dh = values[cursor + 3]
            cursor += 4

            shift = 10 if key in {"title", "objective"} else 26
            resize = 12 if key in {"title", "objective"} else 30
            new_x = int(_clamp(x + dx * shift, 16, CANVAS_WIDTH - 120))
            new_y = int(_clamp(y + dy * shift, 16, CANVAS_HEIGHT - 80))
            new_w = int(_clamp(w + dw * resize, 160, CANVAS_WIDTH - new_x - 16))
            new_h = int(_clamp(h + dh * resize, 58, CANVAS_HEIGHT - new_y - 16))
            slots[key] = {"x": new_x, "y": new_y, "w": new_w, "h": new_h, "rot": 0}

        return SlideLayoutAgent._enforce_slot_guards(slots, constraints or {})

    def run(
        self,
        *,
        content_plan: dict[str, Any],
        template_id: str,
        settings: dict[str, Any],
        title: str,
    ) -> list[dict[str, Any]]:
        slides = content_plan.get("slides", []) if isinstance(content_plan, dict) else []
        pool = self._pool(template_id)
        layout_lookup = _layout_map()
        if not pool:
            pool = [item["id"] for item in LAYOUT_VARIANTS]
        offset = _stable_seed(f"{title}:{template_id}:{len(slides)}") % max(1, len(pool))

        layout_plan: list[dict[str, Any]] = []
        last_layout = ""
        for index, slide in enumerate(slides):
            candidate = pool[(offset + index) % len(pool)]
            if candidate == last_layout and len(pool) > 1:
                candidate = pool[(offset + index + 1) % len(pool)]
            spec = layout_lookup.get(candidate, LAYOUT_VARIANTS[0])
            slot_seed = _stable_seed(f"{title}:{template_id}:{index}:{candidate}")
            layout_plan.append(
                {
                    "slide_id": f"s{index+1}",
                    "slide_index": index,
                    "layout_id": spec["id"],
                    "description": spec["description"],
                    "slots": self._mutate_slots(spec["slots"], slot_seed, spec.get("constraints", {})),
                    "chart_type": spec.get("chart_type", "bar"),
                    "svg_variant": spec.get("svg_variant", "default"),
                    "metric_cards": spec.get("metric_cards", 0),
                    "constraints": spec.get("constraints", {}),
                    "asset_specs": self._asset_specs(slide, spec, template_id, index, attempt=0),
                    "attempt": 0,
                }
            )
            last_layout = candidate

        if len(layout_plan) >= 5:
            unique_before = len({item["layout_id"] for item in layout_plan})
            if unique_before < 3 and len(pool) > 2:
                for index, item in enumerate(layout_plan):
                    if index % 2 == 1:
                        alt = pool[(offset + index + 2) % len(pool)]
                        if alt != item["layout_id"]:
                            spec = layout_lookup[alt]
                            slot_seed = _stable_seed(f"{title}:{template_id}:{index}:{alt}:alt")
                            item["layout_id"] = alt
                            item["description"] = spec["description"]
                            item["slots"] = self._mutate_slots(
                                spec["slots"], slot_seed, spec.get("constraints", {})
                            )
                            item["chart_type"] = spec.get("chart_type", "bar")
                            item["svg_variant"] = spec.get("svg_variant", "default")
                            item["metric_cards"] = spec.get("metric_cards", 0)
                            item["constraints"] = spec.get("constraints", {})
                            slide = slides[index] if index < len(slides) else {}
                            item["asset_specs"] = self._asset_specs(slide, spec, template_id, index, attempt=0)
        return layout_plan

    def replan_slide(
        self,
        *,
        current_layout: dict[str, Any],
        template_id: str,
        slide_payload: dict[str, Any],
        reasons: list[str],
        attempt: int,
    ) -> dict[str, Any]:
        current_id = _coerce_text(current_layout.get("layout_id"))
        slide_index = _as_int(current_layout.get("slide_index"), 0)
        pool = self._pool(template_id)
        layout_lookup = _layout_map()
        candidates = [layout_id for layout_id in pool if layout_id != current_id]
        if not candidates:
            candidates = pool
        seed_text = f"{slide_payload.get('title')}|{attempt}|{','.join(reasons)}"
        idx = _stable_seed(seed_text) % max(1, len(candidates))
        chosen = candidates[idx]
        spec = layout_lookup.get(chosen, LAYOUT_VARIANTS[0])
        return {
            "slide_id": current_layout.get("slide_id"),
            "slide_index": slide_index,
            "layout_id": spec["id"],
            "description": spec["description"],
            "slots": self._mutate_slots(
                spec["slots"],
                _stable_seed(f"{slide_payload.get('title')}|{slide_index}|{attempt}|{chosen}"),
                spec.get("constraints", {}),
            ),
            "chart_type": spec.get("chart_type", "bar"),
            "svg_variant": spec.get("svg_variant", "default"),
            "metric_cards": spec.get("metric_cards", 0),
            "constraints": spec.get("constraints", {}),
            "asset_specs": self._asset_specs(
                slide_payload,
                spec,
                template_id,
                slide_index,
                attempt=attempt,
            ),
            "attempt": attempt,
        }


class SlideComposerAgent:
    @staticmethod
    def _metric_values(points: list[str]) -> list[int]:
        values: list[int] = []
        for point in points[:4]:
            words = len(point.split())
            values.append(int(_clamp((words / 2.0) + 2.0, 2.0, 10.0)))
        while len(values) < 4:
            values.append(3 + len(values))
        return values[:4]

    @staticmethod
    def _constrained_key_points(
        points: list[str],
        constraints: dict[str, Any],
    ) -> list[str]:
        max_bullets = int(_clamp(_as_int(constraints.get("max_bullets"), 4), 1, 6))
        max_line_chars = int(_clamp(_as_int(constraints.get("max_line_chars"), 92), 48, 128))
        constrained: list[str] = []
        for point in points[:max_bullets]:
            constrained.append(_trim_sentence(_coerce_text(point), max_line_chars))
        if not constrained:
            constrained = ["Claim: Core message", "Evidence: Source-backed insight", "Implication: Actionable takeaway"]
        return constrained[:max_bullets]

    @staticmethod
    def _best_contrast_text(background: str, candidates: list[str], min_ratio: float = 4.2) -> str:
        if not candidates:
            return "#0F172A"
        normalized_bg = _normalize_hex_color(background, "#F6F9FF")
        best = _normalize_hex_color(candidates[0], "#0F172A")
        best_ratio = _contrast_ratio(best, normalized_bg)
        for item in candidates[1:]:
            candidate = _normalize_hex_color(item, best)
            ratio = _contrast_ratio(candidate, normalized_bg)
            if ratio > best_ratio:
                best = candidate
                best_ratio = ratio
            if ratio >= min_ratio:
                return candidate
        return best

    @staticmethod
    def _safe_text_slots(
        slots: dict[str, Any],
        template_id: str,
        foreground: str,
        muted: str,
    ) -> dict[str, Any]:
        adjusted = json.loads(json.dumps(slots))
        danger_zone_map = {
            "academic_evidence": {"x": 1180, "color": "#242433"},
            "professional_showcase": {"x": 860, "color": "#121B34"},
        }
        zone = danger_zone_map.get(template_id)
        if not zone:
            return adjusted
        stripe_x = _as_int(zone.get("x"), 1180)
        min_contrast = 4.2
        stripe_color = _normalize_hex_color(zone.get("color"), "#242433")
        if _contrast_ratio(foreground, stripe_color) >= min_contrast and _contrast_ratio(muted, stripe_color) >= min_contrast:
            return adjusted

        safe_right = stripe_x - 28
        for key in ("title", "objective", "bullets", "callout"):
            box = adjusted.get(key)
            if not isinstance(box, dict):
                continue
            x = _as_int(box.get("x"), 0)
            w = _as_int(box.get("w"), 0)
            if x + w > safe_right:
                box["w"] = int(_clamp(safe_right - x, 180, CANVAS_WIDTH - x - 16))
                adjusted[key] = box
        return adjusted

    @staticmethod
    def _should_render_callout(
        *,
        layout_spec: dict[str, Any],
        template_id: str,
        key_points: list[str],
        chart_fallback_needed: bool,
    ) -> bool:
        if not key_points:
            return False
        if chart_fallback_needed:
            return False
        layout_id = _coerce_text(layout_spec.get("layout_id"))
        first_line = _coerce_text(key_points[0])
        if len(first_line) > 128:
            return False
        if template_id == "academic_evidence" and layout_id not in {"focus_statement", "timeline_flow", "workshop_cards"}:
            return False
        if layout_id in {"hero_split_left", "hero_split_right", "comparison_dual", "data_dashboard"}:
            return False
        return True

    @staticmethod
    def _asset_profile(
        *,
        slide_id: str,
        layout_spec: dict[str, Any],
        chart_fallback_needed: bool,
    ) -> dict[str, bool]:
        layout_id = _coerce_text(layout_spec.get("layout_id"))
        slide_idx = max(1, _as_int(re.sub(r"[^0-9]", "", slide_id), 1))

        if chart_fallback_needed:
            # Do not force fake quantitative visuals across every slide.
            if layout_id == "data_dashboard":
                return {"render_image": True, "render_chart": True}
            return {"render_image": True, "render_chart": False}

        if layout_id in {"data_dashboard", "comparison_dual"}:
            return {"render_image": slide_idx % 2 == 1, "render_chart": True}
        if layout_id in {"hero_split_left", "hero_split_right", "timeline_flow"}:
            return {"render_image": True, "render_chart": slide_idx % 3 != 1}
        if layout_id == "focus_statement":
            return {"render_image": True, "render_chart": slide_idx % 2 == 0}
        return {"render_image": True, "render_chart": slide_idx % 2 == 0}

    @staticmethod
    def _citation_footer(citations: list[dict[str, Any]]) -> list[str]:
        footer: list[str] = []
        for item in citations[:4]:
            if not isinstance(item, dict):
                continue
            cid = _coerce_text(item.get("id"))
            short_ref = _coerce_text(item.get("short_ref") or item.get("title") or "Source")
            if not short_ref:
                continue
            prefix = f"[{cid}] " if cid else ""
            footer.append(_trim_sentence(f"{prefix}{short_ref}", 120))
        return footer

    @staticmethod
    def _decor_elements(
        *,
        template_id: str,
        slide_id: str,
        accent: str,
        background: str,
    ) -> list[dict[str, Any]]:
        if template_id == "executive_data_story":
            return [
                {
                    "id": f"{slide_id}_decor_panel",
                    "type": "shape",
                    "box": {"x": 48, "y": 48, "w": 1504, "h": 804, "rot": 0},
                    "style": {
                        "fill": "#13233A",
                        "borderColor": accent,
                        "borderWidth": 1,
                        "cornerRadius": 20,
                        "zIndex": 1,
                        "locked": True,
                        "purpose": "decor",
                    },
                    "content": "",
                }
            ]
        if template_id == "academic_evidence":
            return [
                {
                    "id": f"{slide_id}_decor_stripe",
                    "type": "shape",
                    "box": {"x": 1180, "y": 0, "w": 420, "h": 900, "rot": 0},
                    "style": {
                        "fill": "#242433",
                        "borderColor": "#242433",
                        "borderWidth": 0,
                        "cornerRadius": 0,
                        "zIndex": 1,
                        "locked": True,
                        "purpose": "decor",
                    },
                    "content": "",
                }
            ]
        if template_id == "professional_showcase":
            return [
                {
                    "id": f"{slide_id}_decor_right",
                    "type": "shape",
                    "box": {"x": 860, "y": 0, "w": 740, "h": 900, "rot": 0},
                    "style": {
                        "fill": "#121B34",
                        "borderColor": "#121B34",
                        "borderWidth": 0,
                        "cornerRadius": 0,
                        "zIndex": 1,
                        "locked": True,
                        "purpose": "decor",
                    },
                    "content": "",
                }
            ]
        return [
            {
                "id": f"{slide_id}_decor_soft",
                "type": "shape",
                "box": {"x": 64, "y": 64, "w": 1470, "h": 772, "rot": 0},
                "style": {
                    "fill": background,
                    "borderColor": accent,
                    "borderWidth": 1,
                    "cornerRadius": 18,
                    "zIndex": 1,
                    "locked": True,
                    "purpose": "decor",
                },
                "content": "",
            }
        ]

    def compose_slide(
        self,
        *,
        slide_id: str,
        slide_payload: dict[str, Any],
        layout_spec: dict[str, Any],
        theme: dict[str, Any],
        template_id: str,
        slide_citations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        slots = layout_spec.get("slots", {})
        constraints = layout_spec.get("constraints", {})
        accent = theme["palette"]["accent"]
        background = theme["palette"]["background"]
        foreground = theme["palette"]["foreground"]
        muted = theme["palette"]["muted"]
        slots = self._safe_text_slots(slots, template_id, foreground, muted)
        citations = slide_citations or []
        citation_ids = [
            _coerce_text(item.get("id"))
            for item in citations
            if isinstance(item, dict) and _coerce_text(item.get("id"))
        ]
        title_text = _coerce_text(slide_payload.get("title")) or slide_id.upper()
        max_line_chars = int(_clamp(_as_int(constraints.get("max_line_chars"), 96), 52, 128))
        objective = _trim_sentence(
            _coerce_text(slide_payload.get("objective")) or "Explain concept clearly.",
            min(170, max_line_chars + 48),
        )
        raw_points = _normalize_key_points(
            slide_payload.get("key_points") or [],
            max_items=5,
            fallback_subject=title_text,
        )
        key_points = self._constrained_key_points(raw_points, constraints)
        metric_values = self._metric_values(key_points)
        chart_data_primary = _chart_data_for_slide(
            title_text,
            key_points,
            _stable_seed(f"{slide_id}:{title_text}:chart1"),
            citations=citations,
            allow_synthetic=False,
        )
        chart_data_secondary = _chart_data_for_slide(
            f"{title_text} secondary",
            key_points,
            _stable_seed(f"{slide_id}:{title_text}:chart2"),
            citations=citations,
            allow_synthetic=False,
        )
        chart_fallback_needed = not bool((chart_data_primary.get("series") or []))
        layout_id = _coerce_text(layout_spec.get("layout_id"))
        asset_profile = self._asset_profile(
            slide_id=slide_id,
            layout_spec=layout_spec,
            chart_fallback_needed=chart_fallback_needed,
        )
        render_callout = self._should_render_callout(
            layout_spec=layout_spec,
            template_id=template_id,
            key_points=key_points,
            chart_fallback_needed=chart_fallback_needed,
        )
        citation_footer = self._citation_footer(citations)

        elements: list[dict[str, Any]] = [
            {
                "id": f"{slide_id}_bg",
                "type": "shape",
                "box": {"x": 0, "y": 0, "w": CANVAS_WIDTH, "h": CANVAS_HEIGHT, "rot": 0},
                "style": {
                    "fill": background,
                    "borderColor": background,
                    "borderWidth": 0,
                    "cornerRadius": 0,
                    "zIndex": 0,
                    "locked": True,
                    "purpose": "background",
                },
                "content": "",
            },
            *self._decor_elements(
                template_id=template_id,
                slide_id=slide_id,
                accent=accent,
                background=background,
            ),
            {
                "id": f"{slide_id}_title",
                "type": "text",
                "box": slots.get("title", _slot(90, 80, 860, 120)),
                "style": {
                    "fontSize": 46,
                    "fontWeight": 700,
                    "color": foreground,
                    "zIndex": 6,
                    "textFit": "shrink",
                },
                "content": title_text,
                "evidence_refs": [],
            },
            {
                "id": f"{slide_id}_objective",
                "type": "text",
                "box": slots.get("objective", _slot(92, 216, 820, 72)),
                "style": {
                    "fontSize": 22,
                    "fontWeight": 500,
                    "color": muted,
                    "zIndex": 6,
                    "textFit": "shrink",
                },
                "content": objective,
                "evidence_refs": citation_ids[:1] if citation_ids else [],
            },
            {
                "id": f"{slide_id}_bullets",
                "type": "bullets",
                "box": slots.get("bullets", _slot(96, 308, 760, 360)),
                "style": {
                    "fontSize": 24,
                    "lineHeight": 1.24,
                    "color": foreground,
                    "zIndex": 6,
                    "textFit": "shrink",
                },
                "content": key_points[:5],
                "evidence_refs": citation_ids[:2] if citation_ids else [],
            },
        ]

        callout_box = slots.get("callout")
        if isinstance(callout_box, dict) and render_callout:
            callout_text = _trim_sentence(key_points[0] if key_points else "Key takeaway", max_line_chars)
            callout_fill = _blend_hex(accent, background, 0.18)
            callout_text_color = self._best_contrast_text(
                callout_fill,
                [foreground, "#0F172A", "#F8FAFC"],
            )
            if _contrast_ratio(callout_text_color, callout_fill) < 4.2:
                callout_fill = _blend_hex("#FFFFFF", background, 0.72)
                callout_text_color = self._best_contrast_text(
                    callout_fill,
                    [foreground, "#0F172A", "#F8FAFC"],
                )
            elements.append(
                {
                    "id": f"{slide_id}_callout",
                    "type": "shape",
                    "box": callout_box,
                    "style": {
                        "fill": callout_fill,
                        "borderColor": accent,
                        "borderWidth": 1,
                        "cornerRadius": 16,
                        "color": callout_text_color,
                        "zIndex": 5,
                        "purpose": "callout",
                        "textFit": "shrink",
                    },
                    "content": callout_text,
                }
            )

        metric_cards = _as_int(layout_spec.get("metric_cards"), 0)
        metric_layouts: set[str] = set()
        if metric_cards > 0 and layout_id in metric_layouts:
            card_count = int(_clamp(metric_cards, 1, 4))
            start_x = 98
            y = 728
            card_w = 210
            gap = 18
            for idx in range(card_count):
                card_fill = _blend_hex(accent, background, 0.12)
                card_text_color = self._best_contrast_text(
                    card_fill,
                    [foreground, "#0F172A", "#F8FAFC"],
                )
                elements.append(
                    {
                        "id": f"{slide_id}_metric_{idx+1}",
                        "type": "shape",
                        "box": {"x": start_x + idx * (card_w + gap), "y": y, "w": card_w, "h": 112, "rot": 0},
                        "style": {
                            "fill": card_fill,
                            "borderColor": accent,
                            "borderWidth": 1,
                            "cornerRadius": 14,
                            "color": card_text_color,
                            "zIndex": 5,
                        },
                        "content": f"{key_points[idx % len(key_points)]} ({metric_values[idx % len(metric_values)]})",
                    }
                )

        image_box = slots.get("image")
        image_rendered = False
        if isinstance(image_box, dict):
            bullets_box = slots.get("bullets")
            render_image = bool(asset_profile.get("render_image", True))
            if isinstance(bullets_box, dict) and _boxes_overlap(image_box, bullets_box):
                max_image_h = _as_int(bullets_box.get("y"), CANVAS_HEIGHT - 16) - _as_int(image_box.get("y"), 0) - 12
                if max_image_h >= 120:
                    image_box["h"] = int(_clamp(max_image_h, 120, _as_int(image_box.get("h"), max_image_h)))
                else:
                    if layout_id == "focus_statement":
                        render_image = False
                    else:
                        new_bullets_y = _as_int(image_box.get("y"), 0) + _as_int(image_box.get("h"), 0) + 12
                        bullets_box["y"] = int(
                            _clamp(
                                new_bullets_y,
                                16,
                                CANVAS_HEIGHT - _as_int(bullets_box.get("h"), 120) - 16,
                            )
                        )
            if render_image:
                elements.append(
                    {
                        "id": f"{slide_id}_image",
                        "type": "image",
                        "box": image_box,
                        "style": {"cornerRadius": 20, "borderColor": accent, "borderWidth": 2, "zIndex": 5},
                        "content": "",
                        "src": "",
                        "asset_hint": _trim_sentence(
                            _coerce_text(slide_payload.get("asset_focus")) or f"visual for {title_text}",
                            120,
                        ),
                    }
                )
                image_rendered = True

        chart_box = slots.get("chart")
        render_chart = bool(asset_profile.get("render_chart", True))
        if isinstance(chart_box, dict):
            # Ensure each slide still carries at least one major visual asset.
            if not render_chart and not image_rendered:
                render_chart = True
            if render_chart and chart_fallback_needed:
                elements.append(
                    {
                        "id": f"{slide_id}_chart_fallback",
                        "type": "shape",
                        "box": chart_box,
                        "style": {
                            "fill": _blend_hex(accent, background, 0.12),
                            "borderColor": accent,
                            "borderWidth": 1,
                            "cornerRadius": 12,
                            "color": foreground,
                            "zIndex": 5,
                            "purpose": "chart_fallback",
                        },
                        "content": "Quantitative chart omitted: insufficient numeric evidence in sources.",
                        "evidence_refs": citation_ids[:2],
                    }
                )
            elif render_chart:
                elements.append(
                    {
                        "id": f"{slide_id}_chart",
                        "type": "chart",
                        "box": chart_box,
                        "style": {
                            "chartType": _coerce_text(layout_spec.get("chart_type")) or "bar",
                            "color": accent,
                            "zIndex": 5,
                        },
                        "data": chart_data_primary,
                        "evidence_refs": citation_ids[:2],
                    }
                )

        chart_secondary = slots.get("chart_secondary")
        if isinstance(chart_secondary, dict) and render_chart and not chart_fallback_needed:
            elements.append(
                {
                    "id": f"{slide_id}_chart_2",
                    "type": "chart",
                    "box": chart_secondary,
                    "style": {
                        "chartType": "line",
                        "color": accent,
                        "zIndex": 5,
                    },
                    "data": chart_data_secondary,
                    "evidence_refs": citation_ids[:2],
                }
            )

        return {
            "id": slide_id,
            "title": title_text,
            "notes": _coerce_text(slide_payload.get("speaker_notes")) or objective,
            "elements": elements,
            "critic": {"density": 0.0, "readability": 0.0, "issues": []},
            "layout_id": layout_spec.get("layout_id"),
            "citations": citations,
            "citation_footer": citation_footer,
        }

    def run(
        self,
        *,
        content_plan: dict[str, Any],
        layout_plan: list[dict[str, Any]],
        title: str,
        language: str,
        template_id: str,
        theme: dict[str, Any],
        slide_evidence: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        deck_title = title.strip() or "Slide Generator Pro Deck"
        slides_payload = content_plan.get("slides", []) if isinstance(content_plan, dict) else []
        normalized_template = TEMPLATE_ALIASES.get(template_id, template_id)
        deck: dict[str, Any] = {
            "version": "1.1",
            "deck_id": "",
            "meta": {
                "title": deck_title,
                "language": language or "vi",
                "template_id": normalized_template,
                "template_pack": normalized_template,
                "render_contract": "pptx_first_v1",
                "learning_goals": content_plan.get("learning_goals", []),
            },
            "size": {"width": CANVAS_WIDTH, "height": CANVAS_HEIGHT},
            "theme": theme,
            "slides": [],
        }

        for idx, slide_payload in enumerate(slides_payload, start=1):
            layout_spec = layout_plan[idx - 1] if idx - 1 < len(layout_plan) else LAYOUT_VARIANTS[0]
            slide = self.compose_slide(
                slide_id=f"s{idx}",
                slide_payload=slide_payload if isinstance(slide_payload, dict) else {},
                layout_spec=layout_spec,
                theme=theme,
                template_id=template_id,
                slide_citations=(slide_evidence or {}).get(f"s{idx}", []),
            )
            deck["slides"].append(slide)
        return deck


class SlideGenerateAgent:
    @staticmethod
    def _variant_for_slide(template_id: str, layout_spec: dict[str, Any]) -> str:
        variant = _coerce_text(layout_spec.get("svg_variant"))
        if variant:
            return variant
        if template_id == "executive_data_story":
            return "data_story"
        if template_id == "academic_evidence":
            return "executive"
        if template_id == "professional_showcase":
            return "professional"
        return "default"

    @staticmethod
    async def _llm_svg_data_url(
        *,
        title: str,
        prompt: str,
        accent: str,
        background: str,
        foreground: str,
        model: str | None,
    ) -> str | None:
        if not model:
            return None
        system_prompt = (
            "You generate slide illustration SVGs. "
            "Return ONLY valid SVG markup (no markdown, no explanation). "
            "Use 800x450 canvas, professional visual hierarchy, and no external resources."
        )
        llm_prompt = (
            f"Title: {title}\n"
            f"Prompt: {prompt}\n"
            f"Palette accent: {accent}\n"
            f"Background: {background}\n"
            f"Foreground: {foreground}\n"
            "Constraints: avoid dense text; produce decorative but readable visuals."
        )
        try:
            response = await complete(
                prompt=llm_prompt,
                system_prompt=system_prompt,
                model=model,
                temperature=0.35,
                max_tokens=1800,
            )
        except Exception:
            return None

        svg_match = re.search(r"<svg[\s\S]*?</svg>", _coerce_text(response), re.IGNORECASE)
        if not svg_match:
            return None
        svg = svg_match.group(0)
        from src.security.svg import sanitize_svg
        try:
            svg = sanitize_svg(svg)
        except Exception:
            return None
        if "xmlns=" not in svg.split(">", 1)[0]:
            svg = svg.replace("<svg", "<svg xmlns='http://www.w3.org/2000/svg'", 1)
        encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded}"

    async def run(
        self,
        *,
        deck: dict[str, Any],
        layout_plan: list[dict[str, Any]],
        content_plan: dict[str, Any],
        template_id: str,
        target_slide_ids: list[str] | None = None,
        attempt_map: dict[str, int] | None = None,
    ) -> tuple[dict[str, Any], list[str]]:
        warnings: list[str] = []
        image_model = _preferred_image_model()
        if not image_model:
            warnings.append("IMAGE_MODEL not set; using deterministic local visual assets.")

        targeted = set(target_slide_ids or [])
        if not targeted:
            targeted = {str(slide.get("id")) for slide in deck.get("slides", []) if isinstance(slide, dict)}

        layout_by_slide = {
            _coerce_text(item.get("slide_id")): item
            for item in layout_plan
            if isinstance(item, dict) and _coerce_text(item.get("slide_id"))
        }
        slides_payload = content_plan.get("slides", []) if isinstance(content_plan, dict) else []

        for slide_index, slide in enumerate(deck.get("slides", [])):
            if not isinstance(slide, dict):
                continue
            slide_id = _coerce_text(slide.get("id"))
            if slide_id not in targeted:
                continue
            layout_spec = layout_by_slide.get(slide_id, {})
            slide_payload = slides_payload[slide_index] if slide_index < len(slides_payload) else {}
            key_points = _normalize_key_points(
                _coerce_text(slide_payload).splitlines(),
                max_items=5,
                fallback_subject=_coerce_text(slide_payload),
            )
            if isinstance(slide_payload, dict):
                key_points = _normalize_key_points(
                    slide_payload.get("key_points") or [],
                    max_items=5,
                    fallback_subject=_coerce_text(slide_payload.get("objective")),
                )
            accent = _coerce_text(deck.get("theme", {}).get("palette", {}).get("accent")) or "#2563EB"
            background = _coerce_text(deck.get("theme", {}).get("palette", {}).get("background")) or "#F8FAFC"
            foreground = _coerce_text(deck.get("theme", {}).get("palette", {}).get("foreground")) or "#0F172A"
            variant = self._variant_for_slide(template_id, layout_spec)
            attempt = _as_int((attempt_map or {}).get(slide_id), 0)
            seed = _stable_seed(
                f"{slide_id}|{slide.get('title')}|{layout_spec.get('layout_id')}|{attempt}|{template_id}"
            )
            use_llm_images = bool(image_model) and attempt <= 4

            image_specs = [
                spec
                for spec in (layout_spec.get("asset_specs") or [])
                if isinstance(spec, dict) and spec.get("type") == "image"
            ]
            chart_specs = [
                spec
                for spec in (layout_spec.get("asset_specs") or [])
                if isinstance(spec, dict) and spec.get("type") == "chart"
            ]
            chart_idx = 0

            for element_idx, element in enumerate(slide.get("elements", [])):
                if not isinstance(element, dict):
                    continue
                element_type = _coerce_text(element.get("type"))
                element_seed = seed + ((element_idx + 1) * 97)

                if element_type == "icon" and not _coerce_text(element.get("content")):
                    icon_pool = ["*", "#", "+", "o", "@", "^"]
                    element["content"] = icon_pool[element_seed % len(icon_pool)]

                if element_type == "image":
                    spec = image_specs[0] if image_specs else {}
                    prompt = _trim_sentence(
                        _coerce_text(spec.get("prompt")) or f"visual for {slide.get('title')}",
                        140,
                    )
                    element["asset_hint"] = prompt
                    rendered_src: str | None = None
                    if use_llm_images:
                        rendered_src = await self._llm_svg_data_url(
                            title=_coerce_text(slide.get("title")) or "Slide",
                            prompt=prompt,
                            accent=accent,
                            background=background,
                            foreground=foreground,
                            model=image_model,
                        )
                    element["src"] = rendered_src or _make_svg_data_url(
                        _coerce_text(slide.get("title")) or "Slide",
                        accent=accent,
                        background=background,
                        variant=variant,
                        foreground=foreground,
                        prompt=prompt,
                        seed=element_seed,
                    )
                elif element_type == "chart":
                    spec = chart_specs[chart_idx] if chart_idx < len(chart_specs) else {}
                    chart_seed = element_seed + chart_idx * 13
                    chart_data = _chart_data_for_slide(
                        _coerce_text(slide.get("title")) or f"Slide {slide_index + 1}",
                        key_points,
                        chart_seed,
                        citations=[
                            item
                            for item in (slide.get("citations") or [])
                            if isinstance(item, dict)
                        ],
                        allow_synthetic=False,
                    )
                    style = element.get("style", {}) if isinstance(element.get("style"), dict) else {}
                    if chart_data.get("series"):
                        element["data"] = chart_data
                        style["chartType"] = (
                            _coerce_text(spec.get("chart_type")) or style.get("chartType") or "bar"
                        )
                        element["style"] = style
                    else:
                        element["type"] = "shape"
                        element.pop("data", None)
                        element["style"] = {
                            **style,
                            "fill": _blend_hex(accent, background, 0.12),
                            "borderColor": accent,
                            "borderWidth": 1,
                            "cornerRadius": 12,
                            "color": foreground,
                            "purpose": "chart_fallback",
                        }
                        element["content"] = (
                            "Quantitative chart omitted: insufficient numeric evidence in sources."
                        )
                    chart_idx += 1

        return deck, _dedupe_keep_order(warnings)


class SlideInstructionAgent:
    @staticmethod
    def _slide_numeric_index(slide_id: str) -> int:
        match = re.search(r"(\d+)$", slide_id)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _slide_text_stats(slide: dict[str, Any]) -> dict[str, int]:
        total_chars = 0
        bullet_count = 0
        max_line = 0
        for element in slide.get("elements", []):
            if not isinstance(element, dict):
                continue
            content = element.get("content")
            if isinstance(content, list):
                lines = [_coerce_text(item) for item in content]
            else:
                lines = [_coerce_text(content)] if _coerce_text(content) else []
            if element.get("type") == "bullets":
                bullet_count += len(lines)
            for line in lines:
                total_chars += len(line)
                max_line = max(max_line, len(line))
        return {"total_chars": total_chars, "bullet_count": bullet_count, "max_line": max_line}

    @staticmethod
    def _active_elements(slide: dict[str, Any]) -> list[dict[str, Any]]:
        active: list[dict[str, Any]] = []
        for element in slide.get("elements", []):
            if not isinstance(element, dict):
                continue
            style = element.get("style", {}) if isinstance(element.get("style"), dict) else {}
            if bool(style.get("locked")):
                continue
            if _coerce_text(style.get("purpose")).lower() in {"background", "decor"}:
                continue
            active.append(element)
        return active

    @staticmethod
    def _slide_background_at_point(
        slide: dict[str, Any],
        point_x: float,
        point_y: float,
        default_bg: str = "#F6F9FF",
    ) -> str:
        picked = _normalize_hex_color(default_bg)
        picked_z = -1
        for element in slide.get("elements", []):
            if not isinstance(element, dict):
                continue
            style = element.get("style", {}) if isinstance(element.get("style"), dict) else {}
            if _coerce_text(style.get("purpose")).lower() not in {"background", "decor"}:
                continue
            box = element.get("box", {}) if isinstance(element.get("box"), dict) else {}
            x = _as_float(box.get("x"), 0.0)
            y = _as_float(box.get("y"), 0.0)
            w = _as_float(box.get("w"), 0.0)
            h = _as_float(box.get("h"), 0.0)
            if not (x <= point_x <= x + w and y <= point_y <= y + h):
                continue
            z = _as_int(style.get("zIndex"), 0)
            if z >= picked_z:
                picked_z = z
                picked = _normalize_hex_color(style.get("fill"), picked)
        return picked

    @staticmethod
    def _geometry_and_contrast_issues(slide: dict[str, Any]) -> dict[str, int]:
        active = SlideInstructionAgent._active_elements(slide)
        overflow_count = 0
        overlap_count = 0
        contrast_count = 0

        for element in active:
            if _estimate_text_overflow(element):
                overflow_count += 1

            if element.get("type") in {"text", "bullets", "equation", "shape"}:
                style = element.get("style", {}) if isinstance(element.get("style"), dict) else {}
                color = _normalize_hex_color(style.get("color"), "#0F172A")
                box = element.get("box", {}) if isinstance(element.get("box"), dict) else {}
                center_x = _as_float(box.get("x"), 0.0) + (_as_float(box.get("w"), 0.0) / 2.0)
                center_y = _as_float(box.get("y"), 0.0) + (_as_float(box.get("h"), 0.0) / 2.0)
                if element.get("type") == "shape":
                    shape_fill = _normalize_hex_color(style.get("fill"), "")
                    background = shape_fill or SlideInstructionAgent._slide_background_at_point(
                        slide, center_x, center_y
                    )
                else:
                    background = SlideInstructionAgent._slide_background_at_point(slide, center_x, center_y)
                if _contrast_ratio(color, background) < 4.2:
                    contrast_count += 1

        for idx, left in enumerate(active):
            left_box = left.get("box", {}) if isinstance(left.get("box"), dict) else {}
            for right in active[idx + 1 :]:
                right_box = right.get("box", {}) if isinstance(right.get("box"), dict) else {}
                if _boxes_overlap(left_box, right_box):
                    overlap_count += 1

        return {
            "overflow": overflow_count,
            "overlap": overlap_count,
            "contrast": contrast_count,
        }

    @staticmethod
    def _image_fingerprints(deck: dict[str, Any]) -> Counter:
        fingerprints: Counter = Counter()
        for slide in deck.get("slides", []):
            if not isinstance(slide, dict):
                continue
            for element in slide.get("elements", []):
                if isinstance(element, dict) and element.get("type") == "image":
                    src = _coerce_text(element.get("src"))
                    if src:
                        fingerprints[hashlib.sha1(src.encode("utf-8")).hexdigest()] += 1
        return fingerprints

    @staticmethod
    def _chart_fingerprints(deck: dict[str, Any]) -> Counter:
        fingerprints: Counter = Counter()
        for slide in deck.get("slides", []):
            if not isinstance(slide, dict):
                continue
            for element in slide.get("elements", []):
                if not isinstance(element, dict) or element.get("type") != "chart":
                    continue
                data = element.get("data", {})
                labels = data.get("labels", []) if isinstance(data, dict) else []
                series = data.get("series", []) if isinstance(data, dict) else []
                values = []
                if isinstance(series, list) and series:
                    first = series[0]
                    if isinstance(first, dict) and isinstance(first.get("values"), list):
                        values = [str(item) for item in first.get("values")]
                payload = {"labels": labels, "values": values}
                fingerprint = hashlib.sha1(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest()
                if fingerprint.strip("|"):
                    fingerprints[fingerprint] += 1
        return fingerprints

    @staticmethod
    def _is_decorative_or_locked(element: dict[str, Any]) -> bool:
        if not isinstance(element, dict):
            return True
        style = element.get("style", {}) if isinstance(element.get("style"), dict) else {}
        if bool(style.get("locked")):
            return True
        if _coerce_text(style.get("purpose")).lower() in {"background", "decor"}:
            return True
        return False

    def run(
        self,
        *,
        deck: dict[str, Any],
        layout_plan: list[dict[str, Any]],
        template_id: str,
    ) -> dict[str, Any]:
        layout_by_slide = {
            _coerce_text(item.get("slide_id")): _coerce_text(item.get("layout_id"))
            for item in layout_plan
            if isinstance(item, dict)
        }
        layout_usage = Counter(layout_by_slide.values())
        dominant_layout = ""
        dominant_count = 0
        if layout_usage:
            dominant_layout, dominant_count = layout_usage.most_common(1)[0]

        image_fp = self._image_fingerprints(deck)
        chart_fp = self._chart_fingerprints(deck)
        slide_count = len([slide for slide in deck.get("slides", []) if isinstance(slide, dict)])

        findings: list[dict[str, Any]] = []
        for slide in deck.get("slides", []):
            if not isinstance(slide, dict):
                continue
            slide_id = _coerce_text(slide.get("id"))
            reasons_major: list[str] = []
            reasons_minor: list[str] = []
            stats = self._slide_text_stats(slide)
            geometry = self._geometry_and_contrast_issues(slide)

            if stats["bullet_count"] > 6 or stats["total_chars"] > 920 or stats["max_line"] > 150:
                reasons_major.append("content_density")
            if stats["max_line"] > 110:
                reasons_major.append("readability")
            if geometry["overflow"] > 0:
                reasons_major.append("overflow")
            if geometry["overlap"] > 0:
                reasons_major.append("layout_overlap")
            if geometry["contrast"] > 0:
                reasons_major.append("contrast")

            layout_id = layout_by_slide.get(slide_id, "")
            if (
                slide_count >= 4
                and dominant_layout
                and layout_id == dominant_layout
                and dominant_count >= int(max(2, slide_count * 0.55))
            ):
                reasons_minor.append("layout_repetition")

            has_image = False
            has_chart = False
            for element in slide.get("elements", []):
                if not isinstance(element, dict):
                    continue
                if self._is_decorative_or_locked(element):
                    continue
                if element.get("type") == "image":
                    has_image = True
                    src = _coerce_text(element.get("src"))
                    if src:
                        fp = hashlib.sha1(src.encode("utf-8")).hexdigest()
                        if image_fp[fp] > 1:
                            reasons_minor.append("duplicate_asset")
                if element.get("type") == "chart":
                    has_chart = True
                    data = element.get("data", {})
                    labels = data.get("labels", []) if isinstance(data, dict) else []
                    series = data.get("series", []) if isinstance(data, dict) else []
                    values = []
                    if isinstance(series, list) and series:
                        first = series[0]
                        if isinstance(first, dict) and isinstance(first.get("values"), list):
                            values = [str(item) for item in first.get("values")]
                    payload = {"labels": labels, "values": values}
                    fp = hashlib.sha1(
                        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
                    ).hexdigest()
                    if fp and chart_fp[fp] > 1:
                        reasons_minor.append("duplicate_asset")
                if (
                    element.get("type") == "shape"
                    and _coerce_text(
                        (element.get("style", {}) if isinstance(element.get("style"), dict) else {}).get("purpose")
                    ).lower()
                    == "chart_fallback"
                ):
                    has_chart = True

                evidence_refs = [
                    _coerce_text(item)
                    for item in (element.get("evidence_refs") or [])
                    if _coerce_text(item)
                ]
                if _is_claim_element_for_citation(element):
                    content_text = _coerce_text(element.get("content"))
                    if element.get("type") == "chart":
                        content_text = json.dumps(element.get("data", {}), ensure_ascii=False)
                    if _contains_data_claim(content_text) and not evidence_refs:
                        reasons_major.append("missing_citation")

            if not has_image and not has_chart:
                reasons_major.append("missing_asset")

            if template_id == "professional_showcase":
                has_callout = any(
                    isinstance(element, dict)
                    and element.get("type") == "shape"
                    and "callout" in _coerce_text(element.get("id")).lower()
                    for element in slide.get("elements", [])
                )
                if not has_callout:
                    reasons_minor.append("style_mismatch")

            deduped_major = _dedupe_keep_order(reasons_major)
            deduped_minor = _dedupe_keep_order(reasons_minor)
            deduped = deduped_major + [item for item in deduped_minor if item not in deduped_major]
            if deduped:
                findings.append(
                    {
                        "slide_id": slide_id,
                        "reasons": deduped,
                        "major_reasons": deduped_major,
                        "minor_reasons": deduped_minor,
                        "severity": (len(deduped_major) * 10) + len(deduped_minor),
                    }
                )

        findings.sort(
            key=lambda item: (-_as_int(item.get("severity"), 0), self._slide_numeric_index(_coerce_text(item.get("slide_id"))))
        )
        actionable = findings[: min(6, len(findings))]
        unresolved_major = [
            {
                "slide_id": _coerce_text(item.get("slide_id")),
                "reasons": [reason for reason in item.get("major_reasons", []) if _coerce_text(reason)],
            }
            for item in findings
            if isinstance(item, dict) and item.get("major_reasons")
        ]
        unresolved_minor = [
            {
                "slide_id": _coerce_text(item.get("slide_id")),
                "reasons": [reason for reason in item.get("minor_reasons", []) if _coerce_text(reason)],
            }
            for item in findings
            if isinstance(item, dict) and item.get("minor_reasons")
        ]
        return {
            "approved": len(findings) == 0,
            "issues": findings,
            "slides_to_retry": actionable,
            "unresolved_major": unresolved_major,
            "unresolved_minor": unresolved_minor,
        }


class SlideCriticAgent:
    @staticmethod
    def _is_decorative(element: dict[str, Any], size: dict[str, Any]) -> bool:
        style = element.get("style", {}) if isinstance(element.get("style"), dict) else {}
        purpose = _coerce_text(style.get("purpose")).lower()
        if purpose in {"background", "decor"}:
            return True
        if bool(style.get("hidden")):
            return True

        width = max(1.0, _as_float(size.get("width"), CANVAS_WIDTH))
        height = max(1.0, _as_float(size.get("height"), CANVAS_HEIGHT))
        box = element.get("box", {}) if isinstance(element.get("box"), dict) else {}
        box_w = max(0.0, _as_float(box.get("w"), 0.0))
        box_h = max(0.0, _as_float(box.get("h"), 0.0))
        full_screen = box_w >= width * 0.85 and box_h >= height * 0.85
        if bool(style.get("locked")) and element.get("type") == "shape" and full_screen:
            return True

        element_id = _coerce_text(element.get("id")).lower()
        if any(token in element_id for token in ("_bg", "_decor", "_stripe")):
            return True
        return False

    def _slide_density(self, slide: dict[str, Any], size: dict[str, Any]) -> float:
        width = max(1.0, _as_float(size.get("width"), CANVAS_WIDTH))
        height = max(1.0, _as_float(size.get("height"), CANVAS_HEIGHT))
        total_area = width * height
        used_area = 0.0
        for element in slide.get("elements", []):
            if not isinstance(element, dict):
                continue
            if self._is_decorative(element, size):
                continue
            box = element.get("box", {})
            box_w = max(0.0, _as_float(box.get("w"), 0.0))
            box_h = max(0.0, _as_float(box.get("h"), 0.0))
            multiplier = 1.0
            if element.get("type") == "bullets":
                multiplier = 1.08
            used_area += box_w * box_h * multiplier
        return round(_clamp(used_area / total_area, 0.0, 1.0), 4)

    @staticmethod
    def _slide_readability(slide: dict[str, Any]) -> float:
        penalties = 0.0
        total_chars = 0
        for element in slide.get("elements", []):
            if not isinstance(element, dict):
                continue
            style = element.get("style", {})
            font_size = _as_float(style.get("fontSize"), 24.0)
            if element.get("type") in {"text", "bullets", "equation"} and font_size < 20:
                penalties += 0.08

            content = element.get("content")
            lines = content if isinstance(content, list) else [_coerce_text(content)] if _coerce_text(content) else []
            if element.get("type") == "bullets":
                if isinstance(lines, list) and len(lines) > 6:
                    penalties += 0.10
                for line in lines:
                    if len(_coerce_text(line)) > 115:
                        penalties += 0.06
            total_chars += sum(len(_coerce_text(line)) for line in lines)

        if total_chars > 850:
            penalties += 0.10
        return round(_clamp(1.0 - penalties, 0.2, 1.0), 4)

    def run(self, deck: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        issues: list[dict[str, Any]] = []
        patches: list[dict[str, Any]] = []
        size = deck.get("size", {"width": CANVAS_WIDTH, "height": CANVAS_HEIGHT})
        for slide in deck.get("slides", []):
            if not isinstance(slide, dict):
                continue
            density = self._slide_density(slide, size)
            readability = self._slide_readability(slide)
            slide_issues: list[str] = []
            if density > 0.80:
                slide_issues.append("High visual density; reduce content blocks or resize elements.")
            if readability < 0.68:
                slide_issues.append("Readability is low; increase font size or simplify bullets.")
            critic = {
                "density": density,
                "readability": readability,
                "issues": slide_issues,
            }
            slide["critic"] = critic
            if slide_issues:
                slide_id = _coerce_text(slide.get("id"))
                issues.append({"slide_id": slide_id, "issues": slide_issues})
                if density > 0.80:
                    patches.append(
                        {
                            "op": "suggest",
                            "slide_id": slide_id,
                            "action": "reduce_density",
                            "value": {"target_density": 0.72},
                        }
                    )
                if readability < 0.68:
                    patches.append(
                        {
                            "op": "suggest",
                            "slide_id": slide_id,
                            "action": "increase_font",
                            "value": {"min_font_size": 22},
                        }
                    )
        return deck, issues, patches


class SlideProEngine:
    def __init__(self):
        self.research_agent = SlideResearchAgent()
        self.content_agent = SlideContentAgent()
        self.layout_agent = SlideLayoutAgent()
        self.composer = SlideComposerAgent()
        self.generate_agent = SlideGenerateAgent()
        self.instruction_agent = SlideInstructionAgent()
        self.critic = SlideCriticAgent()

    @staticmethod
    def templates() -> list[dict[str, Any]]:
        return STYLE_PRESETS

    @staticmethod
    def _tokenize_for_match(text: str) -> set[str]:
        tokens = {
            token
            for token in re.findall(r"[a-z0-9]{3,}", _coerce_text(text).lower())
            if token not in {
                "the",
                "and",
                "for",
                "with",
                "from",
                "this",
                "that",
                "slide",
                "using",
                "into",
                "about",
                "what",
                "how",
                "are",
                "was",
                "were",
                "have",
                "has",
                "had",
            }
        }
        return tokens

    @classmethod
    def _assign_slide_evidence(
        cls,
        *,
        content_plan: dict[str, Any],
        evidence_catalog: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        slides = content_plan.get("slides", []) if isinstance(content_plan, dict) else []
        slide_evidence: dict[str, list[dict[str, Any]]] = {}
        if not evidence_catalog or not slides:
            return slide_evidence

        evidence_items: list[dict[str, Any]] = []
        for item in evidence_catalog:
            if not isinstance(item, dict):
                continue
            token_source = " ".join(
                [
                    _coerce_text(item.get("title")),
                    _coerce_text(item.get("short_ref")),
                    _coerce_text(item.get("snippet")),
                    _coerce_text(item.get("doc_name")),
                ]
            )
            evidence_items.append(
                {
                    "item": item,
                    "tokens": cls._tokenize_for_match(token_source),
                    "has_numeric": bool(_extract_metric_values(_coerce_text(item.get("snippet")), max_values=1)),
                }
            )

        if not evidence_items:
            return slide_evidence

        for idx, slide in enumerate(slides):
            if not isinstance(slide, dict):
                continue
            slide_text = " ".join(
                [
                    _coerce_text(slide.get("title")),
                    _coerce_text(slide.get("objective")),
                    " ".join(_normalize_key_points(slide.get("key_points") or [], max_items=5)),
                ]
            )
            slide_tokens = cls._tokenize_for_match(slide_text)
            scored: list[tuple[int, int, int]] = []
            for evidence_idx, evidence in enumerate(evidence_items):
                overlap = len(slide_tokens.intersection(evidence["tokens"]))
                if overlap <= 0:
                    continue
                score = overlap * 3 + (2 if evidence["has_numeric"] else 0)
                scored.append((score, 1 if evidence["has_numeric"] else 0, evidence_idx))
            scored.sort(reverse=True)

            selected: list[dict[str, Any]] = []
            for _, _, evidence_idx in scored[:2]:
                selected.append(evidence_items[evidence_idx]["item"])
            if not selected:
                first = evidence_catalog[idx % len(evidence_catalog)]
                second = evidence_catalog[(idx + 1) % len(evidence_catalog)] if len(evidence_catalog) > 1 else None
                selected = [first]
                if second and second.get("id") != first.get("id"):
                    selected.append(second)
            slide_evidence[f"s{idx+1}"] = selected[:2]
        return slide_evidence

    async def generate(
        self,
        *,
        title: str,
        language: str,
        source_text: str,
        source_records: list[dict[str, Any]] | None,
        instructions: str,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        template_id = _template_id(settings)
        theme = _default_theme(template_id)

        record_context = _records_to_source_context(source_records or [])
        merged_source_text = (source_text or "").strip()
        if record_context:
            merged_source_text = (
                f"{merged_source_text}\n\n{record_context}" if merged_source_text else record_context
            )

        research = await self.research_agent.run(
            title=title,
            language=language,
            source_text=merged_source_text,
            instructions=instructions,
            settings=settings,
        )

        content_plan = await self.content_agent.run(
            title=title,
            language=language,
            source_text=_coerce_text(research.get("source_text")),
            instructions=instructions,
            settings=settings,
            research_context=research,
        )

        raw_evidence = [
            item for item in (research.get("evidence_catalog") or []) if isinstance(item, dict)
        ]
        evidence_catalog: list[dict[str, Any]] = []
        for idx, item in enumerate(raw_evidence, start=1):
            evidence_item = dict(item)
            evidence_item["id"] = evidence_item.get("id") or f"S{idx}"
            evidence_item["short_ref"] = _trim_sentence(
                _coerce_text(
                    evidence_item.get("short_ref")
                    or evidence_item.get("title")
                    or evidence_item.get("doc_name")
                    or evidence_item.get("url")
                    or f"Source {idx}"
                ),
                120,
            )
            evidence_catalog.append(evidence_item)

        layout_plan = self.layout_agent.run(
            content_plan=content_plan,
            template_id=template_id,
            settings=settings,
            title=title,
        )

        slide_evidence = self._assign_slide_evidence(
            content_plan=content_plan,
            evidence_catalog=evidence_catalog,
        )

        deck = self.composer.run(
            content_plan=content_plan,
            layout_plan=layout_plan,
            title=title,
            language=language,
            template_id=template_id,
            theme=theme,
            slide_evidence=slide_evidence,
        )

        attempts = {f"s{idx+1}": 0 for idx in range(len(deck.get("slides", [])))}
        deck, asset_warnings = await self.generate_agent.run(
            deck=deck,
            layout_plan=layout_plan,
            content_plan=content_plan,
            template_id=template_id,
            attempt_map=attempts,
        )

        max_loops = _instruction_max_loops(settings)
        instruction_cycles: list[dict[str, Any]] = []
        global_budget = min(480, max(1, len(deck.get("slides", []))) * max_loops)

        for cycle in range(global_budget):
            review = self.instruction_agent.run(
                deck=deck,
                layout_plan=layout_plan,
                template_id=template_id,
            )
            candidates = [
                item
                for item in review.get("slides_to_retry", [])
                if _as_int(attempts.get(_coerce_text(item.get("slide_id"))), 0) < max_loops
            ]
            candidates.sort(
                key=lambda item: (
                    _as_int(attempts.get(_coerce_text(item.get("slide_id"))), 0),
                    self.instruction_agent._slide_numeric_index(_coerce_text(item.get("slide_id"))),
                )
            )
            if not candidates:
                break

            slide_index_map = {
                _coerce_text(slide.get("id")): idx
                for idx, slide in enumerate(deck.get("slides", []))
                if isinstance(slide, dict)
            }

            updated_slide_ids: list[str] = []
            cycle_report: list[dict[str, Any]] = []
            for item in candidates:
                slide_id = _coerce_text(item.get("slide_id"))
                reasons = [str(reason) for reason in item.get("reasons", []) if str(reason).strip()]
                if not slide_id or slide_id not in slide_index_map:
                    continue
                slide_index = slide_index_map[slide_id]
                attempts[slide_id] = _as_int(attempts.get(slide_id), 0) + 1

                current_content = (
                    content_plan.get("slides", [])[slide_index]
                    if slide_index < len(content_plan.get("slides", []))
                    else {}
                )
                revised_content = self.content_agent.revise_slide(
                    current_content if isinstance(current_content, dict) else {},
                    reasons,
                    attempts[slide_id],
                )
                if slide_index < len(content_plan.get("slides", [])):
                    content_plan["slides"][slide_index] = revised_content

                current_layout = layout_plan[slide_index] if slide_index < len(layout_plan) else {}
                replanned = self.layout_agent.replan_slide(
                    current_layout=current_layout if isinstance(current_layout, dict) else {},
                    template_id=template_id,
                    slide_payload=revised_content,
                    reasons=reasons,
                    attempt=attempts[slide_id],
                )
                if slide_index < len(layout_plan):
                    layout_plan[slide_index] = replanned

                deck["slides"][slide_index] = self.composer.compose_slide(
                    slide_id=slide_id,
                    slide_payload=revised_content,
                    layout_spec=replanned,
                    theme=theme,
                    template_id=template_id,
                    slide_citations=(slide_evidence or {}).get(slide_id, []),
                )

                updated_slide_ids.append(slide_id)
                cycle_report.append(
                    {
                        "slide_id": slide_id,
                        "reasons": reasons,
                        "attempt": attempts[slide_id],
                        "layout_id": replanned.get("layout_id"),
                    }
                )

            if not updated_slide_ids:
                break

            deck, regen_warnings = await self.generate_agent.run(
                deck=deck,
                layout_plan=layout_plan,
                content_plan=content_plan,
                template_id=template_id,
                target_slide_ids=updated_slide_ids,
                attempt_map=attempts,
            )
            asset_warnings.extend(regen_warnings)
            instruction_cycles.append(
                {
                    "cycle": cycle + 1,
                    "updated_slides": cycle_report,
                }
            )

        instruction_final = self.instruction_agent.run(
            deck=deck,
            layout_plan=layout_plan,
            template_id=template_id,
        )
        unresolved = instruction_final.get("issues", [])
        unresolved_major = [
            item for item in instruction_final.get("unresolved_major", []) if isinstance(item, dict)
        ]
        unresolved_minor = [
            item for item in instruction_final.get("unresolved_minor", []) if isinstance(item, dict)
        ]
        if unresolved_major or unresolved_minor:
            unresolved_ids = ", ".join(
                [
                    _coerce_text(item.get("slide_id"))
                    for item in unresolved[:8]
                    if isinstance(item, dict) and _coerce_text(item.get("slide_id"))
                ]
            )
            if unresolved_major:
                asset_warnings.append(
                    "Instruction agent reached loop budget with major issues on slides: "
                    f"{unresolved_ids}"
                )
            else:
                asset_warnings.append(
                    "Instruction agent reached loop budget with minor polish items on slides: "
                    f"{unresolved_ids}"
                )

        deck, critic_issues, critic_patches = self.critic.run(deck)

        distinct_layouts = len(
            {
                _coerce_text(item.get("layout_id"))
                for item in layout_plan
                if isinstance(item, dict) and _coerce_text(item.get("layout_id"))
            }
        )
        slide_total = len(deck.get("slides", []))
        research_enabled = bool(research.get("kb_enabled") or research.get("search_enabled"))
        research_expectation_met = True
        if research.get("kb_enabled") and not research.get("used_kb"):
            research_expectation_met = False
        if research.get("search_enabled") and not research.get("used_search"):
            research_expectation_met = False

        geometry_problem_slides: set[str] = set()
        contrast_problem_slides: set[str] = set()
        for item in instruction_final.get("issues", []):
            if not isinstance(item, dict):
                continue
            slide_id = _coerce_text(item.get("slide_id"))
            reasons = [str(reason).strip() for reason in item.get("reasons", []) if str(reason).strip()]
            if any(reason in {"overflow", "layout_overlap"} for reason in reasons):
                geometry_problem_slides.add(slide_id)
            if "contrast" in reasons:
                contrast_problem_slides.add(slide_id)

        ungrounded_chart_items: list[str] = []
        for slide in deck.get("slides", []):
            if not isinstance(slide, dict):
                continue
            slide_id = _coerce_text(slide.get("id")) or "slide"
            for element in slide.get("elements", []):
                if not isinstance(element, dict):
                    continue
                element_id = _coerce_text(element.get("id")) or _coerce_text(element.get("type"))
                if element.get("type") == "chart":
                    data = element.get("data", {}) if isinstance(element.get("data"), dict) else {}
                    series = data.get("series") if isinstance(data, dict) else []
                    grounded = _as_bool(data.get("grounded"), default=True)
                    if (not grounded) or (not isinstance(series, list)) or (not series):
                        ungrounded_chart_items.append(f"{slide_id}:{element_id}")
                if (
                    element.get("type") == "shape"
                    and _coerce_text(
                        (element.get("style", {}) if isinstance(element.get("style"), dict) else {}).get("purpose")
                    ).lower()
                    == "chart_fallback"
                ):
                    ungrounded_chart_items.append(f"{slide_id}:{element_id}")

        missing_citation_items: list[str] = []
        for slide in deck.get("slides", []):
            if not isinstance(slide, dict):
                continue
            slide_id = _coerce_text(slide.get("id")) or "slide"
            for element in slide.get("elements", []):
                if not isinstance(element, dict):
                    continue
                if not _is_claim_element_for_citation(element):
                    continue
                evidence_refs = [
                    _coerce_text(item)
                    for item in (element.get("evidence_refs") or [])
                    if _coerce_text(item)
                ]
                claim_text = _coerce_text(element.get("content"))
                if element.get("type") == "chart":
                    claim_text = json.dumps(element.get("data", {}), ensure_ascii=False)
                if _contains_data_claim(claim_text) and not evidence_refs:
                    missing_citation_items.append(
                        f"{slide_id}:{_coerce_text(element.get('id')) or element.get('type')}"
                    )
        citation_coverage_ok = len(missing_citation_items) == 0

        quality_checks = [
            {
                "name": "source_material",
                "status": "pass" if merged_source_text else "warn",
                "detail": (
                    "Planner received source text and/or imported notebook records."
                    if merged_source_text
                    else "No source material provided; generation may be generic."
                ),
            },
            {
                "name": "research_agent",
                "status": "pass" if (not research_enabled or research_expectation_met) else "warn",
                "detail": (
                    (
                        "Research agent executed configured retrieval/search "
                        f"(KB: {len(research.get('used_kb_names', []))}, "
                        f"web: {'yes' if research.get('used_search') else 'no'})."
                    )
                    if research.get("used_kb") or research.get("used_search")
                    else (
                        "Research agent was enabled but returned no external context."
                        if research_enabled
                        else "Research agent was disabled by user settings."
                    )
                ),
            },
            {
                "name": "content_agent",
                "status": "pass" if content_plan.get("source") == "llm" else "warn",
                "detail": (
                    "Content generated with LLM."
                    if content_plan.get("source") == "llm"
                    else "Content agent used deterministic fallback."
                ),
            },
            {
                "name": "layout_agent",
                "status": "pass" if distinct_layouts >= min(3, max(1, slide_total)) else "warn",
                "detail": f"Deck uses {distinct_layouts} distinct layouts across {slide_total} slides.",
            },
            {
                "name": "instruction_agent",
                "status": "warn" if unresolved_major else "pass",
                "detail": (
                    f"Instruction agent reported {len(unresolved_major)} major and {len(unresolved_minor)} minor refinements."
                    if unresolved_major or unresolved_minor
                    else "Instruction agent approved all slides within loop budget."
                ),
            },
            {
                "name": "layout_geometry",
                "status": "warn" if geometry_problem_slides else "pass",
                "detail": (
                    f"Geometry checks flagged overflow/overlap on {len(geometry_problem_slides)} slides."
                    if geometry_problem_slides
                    else "No overflow or invalid overlap detected by instruction geometry checks."
                ),
            },
            {
                "name": "contrast",
                "status": "warn" if contrast_problem_slides else "pass",
                "detail": (
                    f"Contrast issues detected on {len(contrast_problem_slides)} slides."
                    if contrast_problem_slides
                    else "Foreground/background contrast checks passed."
                ),
            },
            {
                "name": "chart_grounding",
                "status": "warn" if ungrounded_chart_items else "pass",
                "detail": (
                    f"{len(ungrounded_chart_items)} chart slots lacked grounded quantitative evidence."
                    if ungrounded_chart_items
                    else "All chart slots are grounded in numeric evidence."
                ),
            },
            {
                "name": "citation_coverage",
                "status": "pass" if citation_coverage_ok else "warn",
                "detail": (
                    "All data claims include evidence references."
                    if citation_coverage_ok
                    else f"Found {len(missing_citation_items)} data claims without citation references."
                ),
            },
            {
                "name": "critic",
                "status": "warn" if critic_issues else "pass",
                "detail": "Critic flagged readability/density issues." if critic_issues else "No major issues.",
            },
        ]

        plan_compat = {
            "learning_goals": content_plan.get("learning_goals", []),
            "slides": [
                {
                    "title": _coerce_text(slide.get("title")),
                    "objective": _coerce_text(slide.get("objective")),
                    "key_points": _normalize_key_points(
                        slide.get("key_points") or [],
                        max_items=6,
                        fallback_subject=_coerce_text(slide.get("objective")),
                    ),
                }
                for slide in (content_plan.get("slides", []) if isinstance(content_plan, dict) else [])
                if isinstance(slide, dict)
            ],
            "source": content_plan.get("source", "fallback"),
        }

        return {
            "deck_json": deck,
            "plan": plan_compat,
            "layout_plan": layout_plan,
            "instruction_cycles": instruction_cycles,
            "critic_issues": critic_issues,
            "suggested_patches": critic_patches,
            "quality_checks": quality_checks,
            "research_trace": research.get("research_trace", {}),
            "evidence_catalog": evidence_catalog,
            "slide_evidence": slide_evidence,
            "instruction_report": {
                "unresolved_major": unresolved_major,
                "unresolved_minor": unresolved_minor,
                "attempts_by_slide": attempts,
            },
            "warnings": _dedupe_keep_order(
                [item for item in asset_warnings if isinstance(item, str)]
                + [item for item in research.get("warnings", []) if isinstance(item, str)]
            ),
        }

    def run_critic(self, deck_json: dict[str, Any]) -> dict[str, Any]:
        deck, issues, patches = self.critic.run(deck_json)
        return {
            "deck_json": deck,
            "issues": issues,
            "suggested_patches": patches,
        }


slide_pro_engine = SlideProEngine()
