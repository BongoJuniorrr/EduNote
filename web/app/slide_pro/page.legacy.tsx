"use client";
import { apiFetch } from '@/lib/api';

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  AlignCenter,
  AlignHorizontalJustifyCenter,
  AlignHorizontalJustifyEnd,
  AlignHorizontalJustifyStart,
  AlignVerticalJustifyCenter,
  AlignVerticalJustifyEnd,
  AlignVerticalJustifyStart,
  ArrowLeft,
  BookOpen,
  BringToFront,
  ChartColumn,
  ChevronRight,
  Download,
  FileDown,
  FileJson,
  FileText,
  Image as ImageIcon,
  Layers,
  Loader2,
  Lock,
  Minus,
  MousePointer2,
  PenTool,
  RefreshCw,
  RotateCcw,
  Save,
  Shapes,
  Sparkles,
  Table2,
  Type,
  Unlock,
  Wand2,
  Eye,
  EyeOff,
} from "lucide-react";

import NotebookImportModal from "@/components/NotebookImportModal";
import { apiUrl } from "@/lib/api";
import {
  buildChartSvgDataUrl,
  colorToCss,
  createCanvasToPptTransform,
  colorToPpt,
  estimateTextOverflow,
  hasGroundedChartData,
  isTitleElement,
  previewFontFamily,
  resolveFillColorForPpt,
  resolveBulletSpacingPt,
  resolveWrappedBulletLines,
  resolveWrappedTextLines,
  resolveLineHeight,
  resolveOfficeFont,
  withPptxFit,
} from "@/lib/slidePro/renderContract";
import type {
  SlideElement,
  SlideElementBox,
  SlideElementType,
  SlideProCriticResponse,
  SlideProDeck,
  SlideProEvidenceRef,
  SlideProGenerateResponse,
  SlideProKnowledgeBaseOption,
  SlideProResearchEffort,
  SlideProResearchOptionsResponse,
  SlideProSearchProviderOption,
  SlideProTemplate,
} from "@/types/slidePro";

interface NotebookSummary {
  id: string;
  name: string;
  record_count: number;
}

interface NotebookRecord {
  id: string;
  title: string;
  user_query: string;
  output?: string;
  type: string;
  created_at?: string | number;
  metadata?: Record<string, unknown>;
  source_notebook_id?: string;
}

interface ArtifactMeta {
  file_name: string;
  size_bytes: number;
  content_type: string;
  uploaded_at: string;
  url: string;
}

interface CriticIssue {
  slide_id: string;
  issues: string[];
}

interface DragSession {
  mode: "move" | "resize" | "rotate";
  elementId: string;
  selectedIds: string[];
  startClientX: number;
  startClientY: number;
  initialBoxes: Record<string, SlideElementBox>;
  rotateCenter?: { x: number; y: number };
}

const DEFAULT_SIZE = { width: 1600, height: 900 };
const GRID = 8;
const DEFAULT_TITLE = "Slide Generator Pro Deck";
const DEFAULT_LANGUAGE: "vi" | "en" = "vi";
const DEFAULT_SLIDE_COUNT = 8;
const DEFAULT_TEMPLATE_ID = "academic_evidence";
const DEFAULT_ENABLE_KB_RESEARCH = false;
const DEFAULT_ENABLE_WEB_SEARCH = false;
const DEFAULT_SEARCH_PROVIDER = "perplexity";
const DEFAULT_SEARCH_EFFORT: SlideProResearchEffort = "medium";
const DEFAULT_MAX_INSTRUCTION_LOOPS = 5;
const RENDER_CONTRACT = "pptx_first_v1";

const ELEMENT_TYPES: Array<{ type: SlideElementType; label: string; icon: typeof Type }> = [
  { type: "text", label: "Text", icon: Type },
  { type: "bullets", label: "Bullets", icon: FileText },
  { type: "shape", label: "Shape", icon: Shapes },
  { type: "icon", label: "Icon", icon: Sparkles },
  { type: "image", label: "Image", icon: ImageIcon },
  { type: "chart", label: "Chart", icon: ChartColumn },
  { type: "equation", label: "Equation", icon: PenTool },
  { type: "table", label: "Table", icon: Table2 },
];

function uid(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 8)}`;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function snap(value: number): number {
  return Math.round(value / GRID) * GRID;
}

function asNumber(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function asString(value: unknown, fallback: string): string {
  if (typeof value === "string") return value;
  return fallback;
}

function toLineArray(content: SlideElement["content"]): string[] {
  if (Array.isArray(content)) return content.map((item) => String(item));
  if (typeof content === "string") return content ? [content] : [];
  return [];
}

function toSingleText(content: SlideElement["content"]): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) return content.join("\n");
  return "";
}

function isDataClaimText(text: string): boolean {
  if (!text.trim()) return false;
  return /(\d+(\.\d+)?\s*%|\d+(\.\d+)?|benchmark|accuracy|latency|score|top\s*\d+|x\d+)/i.test(text);
}

function isCitationClaimElement(element: SlideElement): boolean {
  if (["bullets", "chart", "table"].includes(element.type)) return true;
  if (element.type === "shape") {
    return asString(element.style?.purpose, "").trim().toLowerCase() === "chart_fallback";
  }
  if (element.type !== "text") return false;
  if (element.id.toLowerCase().endsWith("_title")) return false;
  const purpose = asString(element.style?.purpose, "").trim().toLowerCase();
  return !["background", "decor"].includes(purpose);
}

function normalizeLegacyAlphaFill(style: Record<string, unknown>): Record<string, unknown> {
  const next = { ...style };
  const rawFill = asString(next.fill, "").trim();
  const match = rawFill.match(/^#?([0-9a-fA-F]{8})$/);
  if (!match) return next;
  const packed = match[1].toUpperCase();
  const rgb = packed.slice(0, 6);
  const alpha = Number.parseInt(packed.slice(6, 8), 16) / 255;
  const existingOpacity = asNumber(next.fillOpacity, Number.NaN);
  const effectiveOpacity = Number.isFinite(existingOpacity)
    ? clamp(existingOpacity * alpha, 0, 1)
    : clamp(alpha, 0, 1);
  next.fill = `#${rgb}`;
  next.fillOpacity = effectiveOpacity;
  return next;
}

function buildCitationFooter(citations: SlideProEvidenceRef[]): string[] {
  return citations
    .slice(0, 4)
    .map((item) => {
      const id = asString(item.id, "").trim();
      const shortRef = asString(item.short_ref, asString(item.title, "Source")).trim();
      if (!shortRef) return "";
      return id ? `[${id}] ${shortRef}` : shortRef;
    })
    .filter(Boolean);
}

function normalizeDeckForRender(
  sourceDeck: SlideProDeck,
  slideEvidenceMap?: Record<string, SlideProEvidenceRef[]>,
): SlideProDeck {
  const cloned = structuredClone(sourceDeck) as SlideProDeck;
  for (const slide of cloned.slides) {
    const slideEvidence = (slideEvidenceMap || {})[slide.id] || [];
    if ((!Array.isArray(slide.citations) || slide.citations.length === 0) && slideEvidence.length > 0) {
      slide.citations = slideEvidence;
    }
    if ((!Array.isArray(slide.citation_footer) || slide.citation_footer.length === 0) && Array.isArray(slide.citations)) {
      slide.citation_footer = buildCitationFooter(slide.citations);
    }
    slide.elements = slide.elements.map((element) => {
      const style = typeof element.style === "object" && element.style ? element.style : {};
      return {
        ...element,
        style: normalizeLegacyAlphaFill(style as Record<string, unknown>) as any,
      };
    });
  }
  return cloned;
}

function coerceText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    return value
      .map((item) => coerceText(item))
      .filter(Boolean)
      .join("\n")
      .trim();
  }
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const preferred = [
      obj.markdown,
      obj.normalized_text,
      obj.text,
      obj.content,
      obj.summary,
      obj.description,
      obj.notes,
    ];
    for (const candidate of preferred) {
      const candidateText = coerceText(candidate);
      if (candidateText) return candidateText;
    }
    try {
      return JSON.stringify(obj, null, 2);
    } catch {
      return "";
    }
  }
  return "";
}

function normalizeImportedRecord(record: NotebookRecord): NotebookRecord {
  const metadata =
    record.metadata && typeof record.metadata === "object"
      ? (record.metadata as Record<string, unknown>)
      : {};
  let output = coerceText(record.output);
  if (!output) {
    output =
      coerceText(metadata.markdown) ||
      coerceText(metadata.normalized_text) ||
      coerceText(metadata.text) ||
      coerceText(metadata.notes) ||
      coerceText(metadata.content);
  }
  return {
    ...record,
    output,
    metadata,
  };
}

function recordToSourceChunk(record: NotebookRecord): string {
  const normalized = normalizeImportedRecord(record);
  const typeLabel = normalized.type ? normalized.type.toUpperCase() : "RECORD";
  const title = coerceText(normalized.title) || "Untitled";
  const query = coerceText(normalized.user_query);
  const body = coerceText(normalized.output);

  const lines: string[] = [`## ${title}`, `Type: ${typeLabel}`];
  if (query) {
    lines.push("", `Prompt: ${query}`);
  }
  if (body) {
    lines.push("", body);
  } else {
    lines.push("", "(No textual output in this record. Use metadata/asset links if needed.)");
  }
  return lines.join("\n");
}

function recordsToSourceText(records: NotebookRecord[]): string {
  return records
    .map((record) => recordToSourceChunk(record))
    .filter(Boolean)
    .join("\n\n---\n\n")
    .trim();
}

function mergeImportedRecords(existing: NotebookRecord[], incoming: NotebookRecord[]): NotebookRecord[] {
  const map = new Map<string, NotebookRecord>();
  for (const record of existing) {
    const key = `${record.source_notebook_id || ""}:${record.id}`;
    map.set(key, normalizeImportedRecord(record));
  }
  for (const record of incoming) {
    const normalized = normalizeImportedRecord(record);
    const key = `${normalized.source_notebook_id || ""}:${normalized.id}`;
    map.set(key, normalized);
  }
  return Array.from(map.values());
}

function isInputLike(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toLowerCase();
  return (
    target.isContentEditable ||
    tag === "input" ||
    tag === "textarea" ||
    tag === "select" ||
    Boolean(target.closest("input, textarea, select, [contenteditable='true']"))
  );
}

function uniqueArtifacts(existing: ArtifactMeta[], incoming: ArtifactMeta[]): ArtifactMeta[] {
  const seen = new Set<string>();
  return [...existing, ...incoming].filter((artifact) => {
    const key = artifact.url || `${artifact.file_name}:${artifact.uploaded_at}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function downloadBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  link.click();
  URL.revokeObjectURL(url);
}

function blobToFile(blob: Blob, fileName: string, contentType: string): File {
  return new File([blob], fileName, {
    type: contentType,
    lastModified: Date.now(),
  });
}

function deckToNotebookMarkdown(deck: SlideProDeck): string {
  const lines: string[] = [`# ${deck.meta.title}`];
  const goals = deck.meta.learning_goals || [];
  if (goals.length > 0) {
    lines.push("", "## Learning Goals");
    for (const goal of goals) {
      lines.push(`- ${goal}`);
    }
  }
  for (const slide of deck.slides) {
    lines.push("", `## ${slide.title}`);
    if (slide.notes) lines.push(slide.notes);
    const bullets: string[] = [];
    for (const element of slide.elements) {
      if (element.type === "bullets") {
        bullets.push(...toLineArray(element.content).slice(0, 8));
      }
    }
    if (bullets.length > 0) {
      lines.push("");
      for (const point of bullets) {
        lines.push(`- ${point}`);
      }
    }
  }
  return lines.join("\n").trim();
}

function createDefaultElement(
  type: SlideElementType,
  index: number,
  deck: SlideProDeck,
): SlideElement {
  const accent = deck.theme.palette.accent;
  const foreground = deck.theme.palette.foreground;
  const baseX = 96 + (index % 4) * 36;
  const baseY = 120 + (index % 3) * 32;
  const id = uid(`e_${type}`);

  if (type === "text") {
    return {
      id,
      type,
      box: { x: baseX, y: baseY, w: 520, h: 88, rot: 0 },
      style: { fontSize: 42, fontWeight: 700, color: foreground, zIndex: 2 },
      content: "Editable title",
    };
  }
  if (type === "bullets") {
    return {
      id,
      type,
      box: { x: baseX, y: baseY + 70, w: 620, h: 320, rot: 0 },
      style: { fontSize: 28, lineHeight: 1.25, color: foreground, zIndex: 2 },
      content: ["Point 1", "Point 2", "Point 3"],
    };
  }
  if (type === "shape") {
    return {
      id,
      type,
      box: { x: baseX + 220, y: baseY + 180, w: 260, h: 180, rot: 0 },
      style: {
        fill: `${accent}22`,
        borderColor: accent,
        borderWidth: 2,
        cornerRadius: 18,
        zIndex: 1,
      },
      content: "Shape note",
    };
  }
  if (type === "icon") {
    return {
      id,
      type,
      box: { x: baseX + 300, y: baseY + 80, w: 120, h: 120, rot: 0 },
      style: { color: accent, fontSize: 76, zIndex: 3 },
      content: "★",
    };
  }
  if (type === "image") {
    return {
      id,
      type,
      box: { x: baseX + 420, y: baseY + 90, w: 520, h: 320, rot: 0 },
      style: {
        cornerRadius: 18,
        borderColor: accent,
        borderWidth: 2,
        background: `${accent}12`,
        zIndex: 1,
      },
      content: "",
      src: "",
      asset_hint: "Drop URL into property panel",
    };
  }
  if (type === "chart") {
    return {
      id,
      type,
      box: { x: baseX + 280, y: baseY + 340, w: 580, h: 250, rot: 0 },
      style: { chartType: "bar", color: accent, zIndex: 2 },
      data: {
        labels: ["A", "B", "C", "D"],
        series: [{ name: "Series", values: [4, 7, 3, 8] }],
      },
    };
  }
  if (type === "equation") {
    return {
      id,
      type,
      box: { x: baseX + 240, y: baseY + 250, w: 620, h: 92, rot: 0 },
      style: { fontSize: 34, color: foreground, zIndex: 2 },
      content: "$$ y = ax^2 + bx + c $$",
    };
  }
  return {
    id,
    type: "table",
    box: { x: baseX + 180, y: baseY + 210, w: 740, h: 280, rot: 0 },
    style: { fontSize: 22, color: foreground, borderColor: "#CBD5E1", zIndex: 2 },
    data: {
      rows: [
        ["Metric", "Current", "Target"],
        ["Retention", "72%", "80%"],
        ["Completion", "68%", "78%"],
      ],
    },
  };
}

async function buildEditablePptx(
  sourceDeck: SlideProDeck,
  slideEvidenceMap: Record<string, SlideProEvidenceRef[]> = {},
): Promise<Blob> {
  const { loadPptxGenJS } = await import("@/lib/pptxBrowser");
  const PptxGenJS = await loadPptxGenJS();
  const deck = withPptxFit(normalizeDeckForRender(sourceDeck, slideEvidenceMap));

  const pptx = new PptxGenJS();
  pptx.layout = "LAYOUT_WIDE";
  pptx.author = "Slide Generator Pro";
  pptx.subject = deck.meta.title;
  pptx.company = "EduNote";

  const transform = createCanvasToPptTransform(deck.size);
  const { toX, toY, toW, toH } = transform;
  const bodyFont = resolveOfficeFont(deck.theme.fonts.body, "body");
  const titleFont = resolveOfficeFont(deck.theme.fonts.title, "title");
  const mutedColor = colorToPpt(deck.theme.palette.muted, "#64748B").color;

  for (const slideData of deck.slides) {
    const slide = pptx.addSlide();
    slide.background = { color: colorToPpt(deck.theme.palette.background, "#FFFFFF").color } as any;
    const slideCitations = Array.isArray(slideData.citations) ? slideData.citations : [];
    const citationFooter = Array.isArray(slideData.citation_footer) ? slideData.citation_footer : [];
    const citationFootnotes = (
      citationFooter.length
        ? citationFooter
        : slideCitations.map((citation) => {
            const id = asString(citation.id, "").trim();
            const shortRef = asString(citation.short_ref, asString(citation.title, "Source")).trim();
            return id ? `[${id}] ${shortRef}` : shortRef;
          })
    ).filter(Boolean);

    const elements = [...slideData.elements].sort(
      (a, b) => asNumber(a.style?.zIndex, 0) - asNumber(b.style?.zIndex, 0),
    );

    for (const element of elements) {
      const box = element.box;
      const x = toX(box.x);
      const y = toY(box.y);
      const w = toW(box.w);
      const h = toH(box.h);
      const rotate = asNumber(box.rot, 0);
      const colorSpec = colorToPpt(element.style?.color, deck.theme.palette.foreground);
      const rawFill = asString(element.style?.fill, "").trim();
      const explicitBlack = /^#?(?:000|000000|00000000)$/i.test(rawFill);
      const resolvedFill = resolveFillColorForPpt(
        element.style?.fill,
        deck.theme.palette.background,
        element.style?.fillOpacity,
      );
      const fillSpec =
        resolvedFill.color === "000000" && rawFill && !explicitBlack
          ? { ...resolvedFill, color: colorToPpt(deck.theme.palette.accent, deck.theme.palette.accent).color }
          : resolvedFill;
      const lineSpec = colorToPpt(element.style?.borderColor, deck.theme.palette.accent);
      const color = colorSpec.color;
      const borderWidth = asNumber(element.style?.borderWidth, 0);
      const fontSize = Math.max(10, Math.round(asNumber(element.style?.fontSize, 24) * 0.75));
      const lineHeight = resolveLineHeight(element);
      const cornerRadiusPx = asNumber(element.style?.cornerRadius, 0);
      const safeCornerRadius = Math.max(0, Math.min(0.14, cornerRadiusPx / 180));
      const shapeType =
        cornerRadiusPx >= 8 && box.w < deck.size.width * 0.9 && box.h < deck.size.height * 0.9
          ? pptx.ShapeType.roundRect
          : pptx.ShapeType.rect;

      if (element.type === "text" || element.type === "equation") {
        const refs =
          Array.isArray(element.evidence_refs) && element.evidence_refs.length > 0
            ? ` [${element.evidence_refs.join(", ")}]`
            : "";
        const preferredFont = isTitleElement(element) ? titleFont : bodyFont;
        const wrappedLines = resolveWrappedTextLines(
          element,
          asNumber(element.style?.fontSize, element.type === "text" ? 36 : 24),
        );
        slide.addText(wrappedLines.join("\n"), {
          x,
          y,
          w,
          h,
          color,
          fontSize,
          bold: asNumber(element.style?.fontWeight, 400) >= 600,
          align: "left",
          valign: "top",
          rotate,
          breakLine: false,
          fit: undefined,
          lineSpacingMultiple: lineHeight,
          fontFace: element.type === "equation" ? "Cambria Math" : preferredFont,
        } as any);
        if (refs) {
          slide.addText(refs, {
            x,
            y: y + Math.max(0, h - 0.25),
            w,
            h: 0.22,
            color: mutedColor,
            fontSize: 10,
            align: "right",
            valign: "bottom",
            fontFace: bodyFont,
          } as any);
        }
        continue;
      }

      if (element.type === "bullets") {
        const wrappedLines = resolveWrappedBulletLines(element, asNumber(element.style?.fontSize, 24));
        const lines = wrappedLines.map((lineItem) => (lineItem.bullet ? `• ${lineItem.text}` : `  ${lineItem.text}`));
        const bulletSpacingPt = resolveBulletSpacingPt(element);
        slide.addText(lines.join("\n"), {
          x,
          y,
          w,
          h,
          color,
          fontSize,
          valign: "top",
          breakLine: false,
          fit: undefined,
          rotate,
          paraSpaceAfterPt: bulletSpacingPt,
          lineSpacingMultiple: lineHeight,
          fontFace: bodyFont,
        } as any);
        if (Array.isArray(element.evidence_refs) && element.evidence_refs.length > 0) {
          slide.addText(`[${element.evidence_refs.join(", ")}]`, {
            x,
            y: y + Math.max(0, h - 0.22),
            w,
            h: 0.2,
            color: mutedColor,
            fontSize: 10,
            align: "right",
            valign: "bottom",
            fontFace: bodyFont,
          } as any);
        }
        continue;
      }

      if (element.type === "shape") {
        const purpose = asString(element.style?.purpose, "").trim().toLowerCase();
        let safeFill = fillSpec;
        if (
          !["background", "decor"].includes(purpose) &&
          safeFill.color === "000000" &&
          (!explicitBlack || typeof safeFill.transparency === "number")
        ) {
          const fallbackAccent = colorToPpt(element.style?.borderColor, deck.theme.palette.accent);
          safeFill = {
            color: fallbackAccent.color,
            transparency: 84,
          };
        }

        const shapeFill: Record<string, unknown> = { color: safeFill.color };
        if (typeof safeFill.transparency === "number") {
          shapeFill.transparency = clamp(safeFill.transparency, 0, 100);
        }
        slide.addShape(shapeType, {
          x,
          y,
          w,
          h,
          rotate,
          rectRadius: safeCornerRadius,
          line: {
            color: lineSpec.color,
            pt: borderWidth > 0 ? borderWidth : 1,
            transparency: lineSpec.transparency,
          },
          fill: shapeFill,
        } as any);
        const caption = toSingleText(element.content);
        if (caption.trim()) {
          slide.addText(caption, {
            x,
            y,
            w,
            h,
            color,
            fontSize: Math.max(12, fontSize - 2),
            valign: "middle",
            align: "center",
            rotate,
            fontFace: bodyFont,
          } as any);
        }
        continue;
      }

      if (element.type === "icon") {
        slide.addText(toSingleText(element.content) || "★", {
          x,
          y,
          w,
          h,
          color,
          fontSize: Math.max(20, fontSize + 16),
          align: "center",
          valign: "middle",
          rotate,
          fontFace: titleFont,
        } as any);
        continue;
      }

      if (element.type === "image") {
        if (typeof element.src === "string" && element.src.startsWith("data:image")) {
          slide.addImage({
            data: element.src,
            x,
            y,
            w,
            h,
            rotate,
          } as any);
        } else {
          const bgSpec = resolveFillColorForPpt(
            element.style?.background,
            "#F8FAFC",
            element.style?.fillOpacity,
          );
          const bgFill: Record<string, unknown> = { color: bgSpec.color };
          if (typeof bgSpec.transparency === "number") {
            bgFill.transparency = clamp(bgSpec.transparency, 0, 100);
          }
          slide.addShape(shapeType, {
            x,
            y,
            w,
            h,
            rotate,
            rectRadius: safeCornerRadius,
            line: {
              color: lineSpec.color,
              pt: borderWidth > 0 ? borderWidth : 1,
              transparency: lineSpec.transparency,
            },
            fill: bgFill,
          } as any);
          slide.addText(
            asString(element.asset_hint, "Image placeholder"),
            {
              x: x + 0.12,
              y: y + h / 2 - 0.2,
              w: Math.max(0.2, w - 0.24),
              h: 0.4,
              color: mutedColor,
              fontSize: Math.max(10, fontSize - 4),
              align: "center",
              valign: "middle",
            } as any,
          );
        }
        continue;
      }

      if (element.type === "chart") {
        const grounded = hasGroundedChartData(element);
        const chartSvgData = buildChartSvgDataUrl(element, {
          accent: asString(element.style?.color, deck.theme.palette.accent),
          foreground: deck.theme.palette.foreground,
          muted: deck.theme.palette.muted,
          background: deck.theme.palette.background,
        });
        if (!grounded || !chartSvgData) {
          const fallbackFill = colorToPpt(element.style?.color, deck.theme.palette.accent);
          slide.addShape(shapeType, {
            x,
            y,
            w,
            h,
            rectRadius: safeCornerRadius,
            line: { color: fallbackFill.color, pt: 1, transparency: fallbackFill.transparency },
            fill: { color: colorToPpt("#E2EEF8", "#E2EEF8").color, transparency: 20 },
          } as any);
          slide.addText("Quantitative chart omitted: insufficient numeric evidence in sources.", {
            x: x + 0.12,
            y: y + h / 2 - 0.25,
            w: Math.max(0.2, w - 0.24),
            h: 0.5,
            color,
            fontSize: Math.max(11, fontSize - 6),
            align: "center",
            valign: "middle",
            fontFace: bodyFont,
            breakLine: true,
          } as any);
          if (Array.isArray(element.evidence_refs) && element.evidence_refs.length > 0) {
            slide.addText(`[${element.evidence_refs.join(", ")}]`, {
              x,
              y: y + Math.max(0, h - 0.22),
              w,
              h: 0.2,
              color: mutedColor,
              fontSize: 10,
              align: "right",
              valign: "bottom",
              fontFace: bodyFont,
            } as any);
          }
          continue;
        }

        slide.addImage({
          data: chartSvgData,
          x,
          y,
          w,
          h,
        } as any);
        if (Array.isArray(element.evidence_refs) && element.evidence_refs.length > 0) {
          slide.addText(`[${element.evidence_refs.join(", ")}]`, {
            x,
            y: y + Math.max(0, h - 0.22),
            w,
            h: 0.2,
            color: mutedColor,
            fontSize: 10,
            align: "right",
            valign: "bottom",
            fontFace: bodyFont,
          } as any);
        }
        continue;
      }

      if (element.type === "table") {
        const rowsRaw = Array.isArray(element.data?.rows) ? element.data?.rows : [];
        const rows = rowsRaw
          .filter((row): row is unknown[] => Array.isArray(row))
          .map((row) => row.map((cell) => ({ text: String(cell) })));
        if (rows.length > 0) {
          const borderSpec = colorToPpt(element.style?.borderColor, "#94A3B8");
          slide.addTable(rows, {
            x,
            y,
            w,
            h,
            fontSize,
            color,
            border: {
              pt: 1,
              color: borderSpec.color,
              type: "solid",
            },
          } as any);
        }
      }
    }

    if (citationFootnotes.length > 0) {
      const footerTokens = citationFootnotes.slice(0, 3);
      if (citationFootnotes.length > 3) {
        footerTokens.push(`+${citationFootnotes.length - 3} more`);
      }
      slide.addText(footerTokens.join("  "), {
        x: 0.45,
        y: 7.2,
        w: 12.4,
        h: 0.2,
        color: mutedColor,
        fontSize: 9,
        align: "left",
        valign: "bottom",
        fontFace: bodyFont,
      } as any);
      const noteRows = slideCitations.length
        ? slideCitations.map((citation) => {
            const id = asString(citation.id, "");
            const shortRef = asString(citation.short_ref, asString(citation.title, "Source"));
            const url = asString(citation.url, "");
            return `${id ? `[${id}] ` : ""}${shortRef}${url ? ` - ${url}` : ""}`;
          })
        : citationFootnotes;
      const notesText = [
        "Sources:",
        ...noteRows,
      ].join("\n");
      slide.addNotes(notesText);
    }
  }

  return (await pptx.write({ outputType: "blob" })) as Blob;
}

export default function SlideProPage() {
  const [title, setTitle] = useState(DEFAULT_TITLE);
  const [language, setLanguage] = useState<"vi" | "en">(DEFAULT_LANGUAGE);
  const [sourceText, setSourceText] = useState("");
  const [instructions, setInstructions] = useState("");
  const [slideCount, setSlideCount] = useState(DEFAULT_SLIDE_COUNT);
  const [maxInstructionLoops, setMaxInstructionLoops] = useState(DEFAULT_MAX_INSTRUCTION_LOOPS);
  const [selectedTemplateId, setSelectedTemplateId] = useState(DEFAULT_TEMPLATE_ID);
  const [enableKbResearch, setEnableKbResearch] = useState(DEFAULT_ENABLE_KB_RESEARCH);
  const [enableWebSearch, setEnableWebSearch] = useState(DEFAULT_ENABLE_WEB_SEARCH);
  const [knowledgeBaseOptions, setKnowledgeBaseOptions] = useState<SlideProKnowledgeBaseOption[]>([]);
  const [selectedKbNames, setSelectedKbNames] = useState<string[]>([]);
  const [defaultKbNames, setDefaultKbNames] = useState<string[]>([]);
  const [searchProviderOptions, setSearchProviderOptions] = useState<SlideProSearchProviderOption[]>([]);
  const [searchProvider, setSearchProvider] = useState(DEFAULT_SEARCH_PROVIDER);
  const [defaultSearchProvider, setDefaultSearchProvider] = useState(DEFAULT_SEARCH_PROVIDER);
  const [searchEffort, setSearchEffort] = useState<SlideProResearchEffort>(DEFAULT_SEARCH_EFFORT);
  const [templates, setTemplates] = useState<SlideProTemplate[]>([]);
  const [deck, setDeck] = useState<SlideProDeck | null>(null);
  const [runId, setRunId] = useState("");
  const [artifactBaseUrl, setArtifactBaseUrl] = useState("");
  const [artifacts, setArtifacts] = useState<ArtifactMeta[]>([]);
  const [criticIssues, setCriticIssues] = useState<CriticIssue[]>([]);
  const [suggestedPatches, setSuggestedPatches] = useState<Array<Record<string, unknown>>>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [qualityChecks, setQualityChecks] = useState<
    Array<{ name: string; status: string; detail: string }>
  >([]);
  const [researchTrace, setResearchTrace] = useState<SlideProGenerateResponse["research_trace"] | null>(null);
  const [evidenceCatalog, setEvidenceCatalog] = useState<SlideProEvidenceRef[]>([]);
  const [slideEvidenceMap, setSlideEvidenceMap] = useState<Record<string, SlideProEvidenceRef[]>>({});
  const [instructionReport, setInstructionReport] = useState<SlideProGenerateResponse["instruction_report"] | null>(null);
  const [loadingGenerate, setLoadingGenerate] = useState(false);
  const [loadingCritic, setLoadingCritic] = useState(false);
  const [loadingExportPptx, setLoadingExportPptx] = useState(false);
  const [loadingSaveNotebook, setLoadingSaveNotebook] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [activeSlideIndex, setActiveSlideIndex] = useState(0);
  const [selectedElementIds, setSelectedElementIds] = useState<string[]>([]);
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [selectedNotebookId, setSelectedNotebookId] = useState("");
  const [showNotebookImport, setShowNotebookImport] = useState(false);
  const [importedRecords, setImportedRecords] = useState<NotebookRecord[]>([]);
  const [stageViewport, setStageViewport] = useState({ width: 980, height: 620 });

  const stageContainerRef = useRef<HTMLDivElement | null>(null);
  const stageSurfaceRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<DragSession | null>(null);
  const activeSlideIndexRef = useRef(0);
  const stageScaleRef = useRef(1);

  useEffect(() => {
    activeSlideIndexRef.current = activeSlideIndex;
  }, [activeSlideIndex]);

  const renderDeck = useMemo(() => {
    if (!deck) return null;
    return withPptxFit(normalizeDeckForRender(deck, slideEvidenceMap));
  }, [deck, slideEvidenceMap]);

  const activeSlide = useMemo(() => {
    if (!renderDeck) return null;
    return renderDeck.slides[activeSlideIndex] || null;
  }, [renderDeck, activeSlideIndex]);

  const selectedElements = useMemo(() => {
    if (!activeSlide) return [];
    const wanted = new Set(selectedElementIds);
    return activeSlide.elements.filter((item) => wanted.has(item.id));
  }, [activeSlide, selectedElementIds]);

  const selectedSingleElement = selectedElements.length === 1 ? selectedElements[0] : null;

  const stageScale = useMemo(() => {
    if (!deck) return 1;
    const sx = stageViewport.width / Math.max(1, deck.size.width);
    const sy = stageViewport.height / Math.max(1, deck.size.height);
    return clamp(Math.min(sx, sy), 0.2, 1);
  }, [deck, stageViewport]);

  useEffect(() => { stageScaleRef.current = stageScale; }, [stageScale]);

  const issueMap = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const issue of criticIssues) {
      map.set(issue.slide_id, issue.issues);
    }
    return map;
  }, [criticIssues]);

  const currentTemplate = useMemo(
    () => templates.find((item) => item.id === selectedTemplateId) || null,
    [templates, selectedTemplateId],
  );

  const currentSearchProviderOption = useMemo(
    () => searchProviderOptions.find((item) => item.id === searchProvider) || null,
    [searchProviderOptions, searchProvider],
  );

  const activeSlideEvidence = useMemo(() => {
    if (!activeSlide) return [];
    const fromMap = slideEvidenceMap[activeSlide.id] || [];
    if (fromMap.length > 0) return fromMap;
    if (Array.isArray(activeSlide.citations) && activeSlide.citations.length > 0) {
      return activeSlide.citations;
    }
    return evidenceCatalog.slice(0, 3);
  }, [activeSlide, slideEvidenceMap, evidenceCatalog]);

  const activeSlideMissingCitationClaims = useMemo(() => {
    if (!activeSlide) return [];
    const misses: string[] = [];
    for (const element of activeSlide.elements) {
      if (!isCitationClaimElement(element)) continue;
      const refs = Array.isArray(element.evidence_refs)
        ? element.evidence_refs.map((item) => String(item).trim()).filter(Boolean)
        : [];
      if (refs.length > 0) continue;
      let claimText = "";
      if (element.type === "bullets") {
        claimText = toLineArray(element.content).join(" ");
      } else if (element.type === "chart") {
        claimText = JSON.stringify(element.data || {});
      } else {
        claimText = toSingleText(element.content);
      }
      if (!isDataClaimText(claimText)) continue;
      misses.push(`${element.id}: ${claimText.slice(0, 92)}${claimText.length > 92 ? "..." : ""}`);
    }
    return misses.slice(0, 6);
  }, [activeSlide]);

  const updateActiveSlide = useCallback(
    (updater: (slide: SlideProDeck["slides"][number]) => SlideProDeck["slides"][number]) => {
      setDeck((prev) => {
        if (!prev) return prev;
        if (!prev.slides[activeSlideIndexRef.current]) return prev;
        const nextSlides = prev.slides.map((slide, index) =>
          index === activeSlideIndexRef.current ? updater(slide) : slide,
        );
        return { ...prev, slides: nextSlides };
      });
    },
    [],
  );

  const patchElement = useCallback(
    (
      elementId: string,
      updater: (element: SlideElement) => SlideElement,
      targetSlideIndex?: number,
    ) => {
      setDeck((prev) => {
        if (!prev) return prev;
        const idx = targetSlideIndex ?? activeSlideIndexRef.current;
        const slide = prev.slides[idx];
        if (!slide) return prev;
        const nextElements = slide.elements.map((element) =>
          element.id === elementId ? updater(element) : element,
        );
        const nextSlides = prev.slides.map((item, slideIndex) =>
          slideIndex === idx ? { ...item, elements: nextElements } : item,
        );
        return { ...prev, slides: nextSlides };
      });
    },
    [],
  );

  const runCritic = useCallback(async () => {
    if (!deck) return;
    setLoadingCritic(true);
    setError("");
    setNotice("");
    try {
      const response = await apiFetch(apiUrl("/api/v1/slide-pro/critic"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ deck_json: deck }),
      });
      const payload = (await response.json()) as SlideProCriticResponse & { detail?: string };
      if (!response.ok) {
        throw new Error(payload.detail || "Critic failed.");
      }
      setDeck(payload.deck_json);
      setCriticIssues(payload.issues || []);
      setSuggestedPatches(payload.suggested_patches || []);
      setNotice("Critic re-run completed.");
    } catch (criticError: unknown) {
      const message = criticError instanceof Error ? criticError.message : "Critic failed.";
      setError(message);
    } finally {
      setLoadingCritic(false);
    }
  }, [deck]);

  const applySuggestedPatches = useCallback(() => {
    if (!deck || suggestedPatches.length === 0) return;
    setDeck((prev) => {
      if (!prev) return prev;
      const next = structuredClone(prev) as SlideProDeck;
      for (const patch of suggestedPatches) {
        const action = asString(patch.action, "");
        const slideId = asString(patch.slide_id, "");
        const slide = next.slides.find((item) => item.id === slideId);
        if (!slide) continue;
        if (action === "increase_font") {
          const minSize = asNumber(
            (patch.value as Record<string, unknown> | undefined)?.min_font_size,
            22,
          );
          slide.elements = slide.elements.map((element) => {
            if (element.type === "text" || element.type === "bullets" || element.type === "equation") {
              return {
                ...element,
                style: {
                  ...element.style,
                  fontSize: Math.max(asNumber(element.style?.fontSize, minSize), minSize),
                },
              };
            }
            return element;
          });
        } else if (action === "reduce_density") {
          slide.elements = slide.elements.map((element) => {
            if (element.type === "bullets") {
              const bullets = toLineArray(element.content).slice(0, 5);
              return { ...element, content: bullets };
            }
            return element;
          });
        }
      }
      return next;
    });
    setNotice("Applied critic suggestions.");
  }, [deck, suggestedPatches]);

  const uploadArtifacts = useCallback(
    async (files: File[], manifest: Record<string, unknown>) => {
      if (!runId || files.length === 0) return;
      const form = new FormData();
      form.append("manifest", JSON.stringify(manifest));
      for (const file of files) {
        form.append("files", file);
      }

      const response = await apiFetch(apiUrl(`/api/v1/slide-pro/runs/${runId}/artifacts`), {
        method: "POST",
        body: form,
      });
      const payload = (await response.json()) as {
        success?: boolean;
        artifacts?: ArtifactMeta[];
        detail?: string;
      };
      if (!response.ok || !payload.success) {
        throw new Error(payload.detail || "Artifact upload failed.");
      }
      setArtifacts((prev) => uniqueArtifacts(prev, payload.artifacts || []));
    },
    [runId],
  );

  const toggleKnowledgeBase = useCallback((kbName: string) => {
    setSelectedKbNames((prev) => {
      if (prev.includes(kbName)) {
        return prev.filter((item) => item !== kbName);
      }
      return [...prev, kbName];
    });
  }, []);

  const handleClearWorkspace = useCallback(() => {
    const defaultSelectedKbNames = (() => {
      const fromState = defaultKbNames.filter((name) =>
        knowledgeBaseOptions.some((item) => item.name === name),
      );
      if (fromState.length > 0) return fromState;
      const fromOptions = knowledgeBaseOptions.filter((item) => item.is_default).map((item) => item.name);
      if (fromOptions.length > 0) return fromOptions;
      return knowledgeBaseOptions[0] ? [knowledgeBaseOptions[0].name] : [];
    })();
    const hasWorkingState =
      Boolean(deck) ||
      Boolean(sourceText.trim()) ||
      Boolean(instructions.trim()) ||
      enableKbResearch ||
      enableWebSearch ||
      selectedKbNames.join("|") !== defaultSelectedKbNames.join("|") ||
      searchProvider !== defaultSearchProvider ||
      searchEffort !== DEFAULT_SEARCH_EFFORT ||
      maxInstructionLoops !== DEFAULT_MAX_INSTRUCTION_LOOPS ||
      importedRecords.length > 0 ||
      artifacts.length > 0 ||
      Boolean(runId);

    if (
      hasWorkingState &&
      typeof window !== "undefined" &&
      !window.confirm("Clear current Slide Pro workspace and reset all generated results?")
    ) {
      return;
    }

    const defaultTemplateId = templates.some((item) => item.id === DEFAULT_TEMPLATE_ID)
      ? DEFAULT_TEMPLATE_ID
      : templates[0]?.id || DEFAULT_TEMPLATE_ID;

    setTitle(DEFAULT_TITLE);
    setLanguage(DEFAULT_LANGUAGE);
    setSourceText("");
    setInstructions("");
    setSlideCount(DEFAULT_SLIDE_COUNT);
    setMaxInstructionLoops(DEFAULT_MAX_INSTRUCTION_LOOPS);
    setEnableKbResearch(DEFAULT_ENABLE_KB_RESEARCH);
    setEnableWebSearch(DEFAULT_ENABLE_WEB_SEARCH);
    setSelectedKbNames(defaultSelectedKbNames);
    setSearchProvider(defaultSearchProvider || DEFAULT_SEARCH_PROVIDER);
    setSearchEffort(DEFAULT_SEARCH_EFFORT);
    setSelectedTemplateId(defaultTemplateId);
    setDeck(null);
    setRunId("");
    setArtifactBaseUrl("");
    setArtifacts([]);
    setCriticIssues([]);
    setSuggestedPatches([]);
    setWarnings([]);
    setQualityChecks([]);
    setResearchTrace(null);
    setEvidenceCatalog([]);
    setSlideEvidenceMap({});
    setInstructionReport(null);
    setImportedRecords([]);
    setSelectedElementIds([]);
    setActiveSlideIndex(0);
    setError("");
    setNotice("Workspace cleared.");
  }, [
    artifacts.length,
    deck,
    defaultKbNames,
    defaultSearchProvider,
    enableKbResearch,
    enableWebSearch,
    importedRecords.length,
    instructions,
    knowledgeBaseOptions,
    maxInstructionLoops,
    runId,
    searchEffort,
    searchProvider,
    selectedKbNames,
    sourceText,
    templates,
  ]);

  const handleGenerate = useCallback(async () => {
    setLoadingGenerate(true);
    setError("");
    setNotice("");
    try {
      const response = await apiFetch(apiUrl("/api/v1/slide-pro/generate"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          language,
          source_text: sourceText,
          source_records: importedRecords.map((record) => ({
            id: record.id,
            type: record.type,
            title: record.title,
            user_query: record.user_query,
            output: record.output || "",
            created_at: record.created_at,
            source_notebook_id: record.source_notebook_id || "",
            metadata: record.metadata || {},
          })),
          instructions,
          settings: {
            slide_count: slideCount,
            template_id: selectedTemplateId,
            style: selectedTemplateId,
            enable_kb_research: enableKbResearch,
            enable_web_search: enableWebSearch,
            kb_names: selectedKbNames,
            kb_name: selectedKbNames[0] || "",
            search_provider: searchProvider || DEFAULT_SEARCH_PROVIDER,
            search_effort: searchEffort,
            max_instruction_loops: clamp(maxInstructionLoops, 1, 20),
          },
        }),
      });
      const payload = (await response.json()) as SlideProGenerateResponse & { detail?: string };
      if (!response.ok || !payload.success) {
        throw new Error(payload.detail || "Failed to generate deck.");
      }
      setDeck(payload.deck_json);
      setRunId(payload.run_id);
      setArtifactBaseUrl(payload.artifact_base_url);
      setArtifacts(payload.artifacts || []);
      setCriticIssues(payload.critic_issues || []);
      setSuggestedPatches(payload.suggested_patches || []);
      setWarnings(payload.warnings || []);
      setQualityChecks(payload.quality_checks || []);
      setResearchTrace(payload.research_trace || null);
      setEvidenceCatalog(payload.evidence_catalog || []);
      setSlideEvidenceMap(payload.slide_evidence || {});
      setInstructionReport(payload.instruction_report || null);
      setActiveSlideIndex(0);
      setSelectedElementIds([]);
      setNotice(`Generated ${payload.deck_json.slides.length} editable slides.`);
    } catch (generateError: unknown) {
      const message = generateError instanceof Error ? generateError.message : "Generate failed.";
      setError(message);
    } finally {
      setLoadingGenerate(false);
    }
  }, [
    title,
    language,
    sourceText,
    importedRecords,
    instructions,
    slideCount,
    maxInstructionLoops,
    enableKbResearch,
    enableWebSearch,
    selectedKbNames,
    searchProvider,
    searchEffort,
    selectedTemplateId,
  ]);

  const handleExportJson = useCallback(async () => {
    if (!deck) return;
    setError("");
    setNotice("");
    try {
      const fileName = `${deck.deck_id || runId || "slide_pro"}.slidepro.json`;
      const payload = {
        deck_json: deck,
        render_contract: RENDER_CONTRACT,
        research_trace: researchTrace || {},
        evidence_catalog: evidenceCatalog,
        slide_evidence: slideEvidenceMap,
        instruction_report: instructionReport || {},
      };
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
      downloadBlob(blob, fileName);
      if (runId) {
        await uploadArtifacts(
          [blobToFile(blob, fileName, "application/json")],
          {
            kind: "slidepro_json",
            deck_id: deck.deck_id,
            slide_count: deck.slides.length,
          },
        );
      }
      setNotice("Deck JSON exported.");
    } catch (exportError: unknown) {
      const message = exportError instanceof Error ? exportError.message : "JSON export failed.";
      setError(message);
    }
  }, [deck, runId, uploadArtifacts, researchTrace, evidenceCatalog, slideEvidenceMap, instructionReport]);

  const handleExportPptx = useCallback(async () => {
    if (!deck) return;
    setLoadingExportPptx(true);
    setError("");
    setNotice("");
    try {
      const pptxBlob = await buildEditablePptx(deck, slideEvidenceMap);
      const fileName = `${deck.deck_id || runId || "slide_pro"}.pptx`;
      downloadBlob(pptxBlob, fileName);
      if (runId) {
        await uploadArtifacts(
          [
            blobToFile(
              pptxBlob,
              fileName,
              "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ),
          ],
          {
            kind: "slidepro_pptx",
            mode: "editable_objects",
            slide_count: deck.slides.length,
          },
        );
      }
      setNotice("Editable PPTX exported.");
    } catch (exportError: unknown) {
      const message = exportError instanceof Error ? exportError.message : "PPTX export failed.";
      setError(message);
    } finally {
      setLoadingExportPptx(false);
    }
  }, [deck, runId, uploadArtifacts, slideEvidenceMap]);

  const handleSaveToNotebook = useCallback(async () => {
    if (!deck || !selectedNotebookId) return;
    setLoadingSaveNotebook(true);
    setError("");
    setNotice("");
    try {
      const deckJsonArtifact = artifacts.find((item) => item.file_name.endsWith(".slidepro.json"));
      const pptxArtifact = artifacts.find((item) => item.file_name.endsWith(".pptx"));
      const output = deckToNotebookMarkdown(deck);
      const response = await apiFetch(apiUrl("/api/v1/notebook/add_record"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          notebook_ids: [selectedNotebookId],
          record_type: "slide_pro",
          title: deck.meta.title || title || "Slide Generator Pro Deck",
          user_query: `Slide Generator Pro run ${runId || deck.deck_id}`,
          output,
          metadata: {
            source: "slide_pro",
            run_id: runId,
            deck_id: deck.deck_id,
            template_id: deck.meta.template_id,
            language: deck.meta.language,
            slide_count: deck.slides.length,
            artifact_base_url: artifactBaseUrl,
            artifact_urls: artifacts.map((item) => item.url),
            slidepro_json_url: deckJsonArtifact?.url || "",
            pptx_url: pptxArtifact?.url || "",
            quality_checks: qualityChecks,
            research_trace: researchTrace || {},
            evidence_catalog: evidenceCatalog,
            slide_evidence: slideEvidenceMap,
            instruction_report: instructionReport || {},
            render_contract: deck.meta.render_contract || RENDER_CONTRACT,
          },
        }),
      });
      const payload = (await response.json()) as { success?: boolean; detail?: string };
      if (!response.ok || !payload.success) {
        throw new Error(payload.detail || "Save to notebook failed.");
      }
      setNotice("Saved as notebook record type slide_pro.");
    } catch (saveError: unknown) {
      const message = saveError instanceof Error ? saveError.message : "Save to notebook failed.";
      setError(message);
    } finally {
      setLoadingSaveNotebook(false);
    }
  }, [
    deck,
    selectedNotebookId,
    runId,
    title,
    artifactBaseUrl,
    artifacts,
    qualityChecks,
    researchTrace,
    evidenceCatalog,
    slideEvidenceMap,
    instructionReport,
  ]);

  const addElement = useCallback(
    (type: SlideElementType) => {
      if (!deck || !activeSlide) return;
      const nextElement = createDefaultElement(type, activeSlide.elements.length, deck);
      updateActiveSlide((slide) => ({
        ...slide,
        elements: [...slide.elements, nextElement],
      }));
      setSelectedElementIds([nextElement.id]);
    },
    [deck, activeSlide, updateActiveSlide],
  );

  const removeSelectedElements = useCallback(() => {
    if (!activeSlide || selectedElementIds.length === 0) return;
    const selected = new Set(selectedElementIds);
    updateActiveSlide((slide) => ({
      ...slide,
      elements: slide.elements.filter((element) => !selected.has(element.id)),
    }));
    setSelectedElementIds([]);
  }, [activeSlide, selectedElementIds, updateActiveSlide]);

  const duplicateSelected = useCallback(() => {
    if (!activeSlide || selectedElementIds.length === 0) return;
    const selected = new Set(selectedElementIds);
    const clones: SlideElement[] = [];
    for (const element of activeSlide.elements) {
      if (!selected.has(element.id)) continue;
      clones.push({
        ...element,
        id: uid("dup"),
        box: {
          ...element.box,
          x: clamp(snap(element.box.x + 24), 0, (deck?.size.width || DEFAULT_SIZE.width) - element.box.w),
          y: clamp(snap(element.box.y + 20), 0, (deck?.size.height || DEFAULT_SIZE.height) - element.box.h),
        },
      });
    }
    if (clones.length === 0) return;
    updateActiveSlide((slide) => ({ ...slide, elements: [...slide.elements, ...clones] }));
    setSelectedElementIds(clones.map((item) => item.id));
  }, [activeSlide, selectedElementIds, updateActiveSlide, deck]);

  const nudgeSelected = useCallback(
    (dx: number, dy: number) => {
      if (!deck || !activeSlide || selectedElementIds.length === 0) return;
      const selected = new Set(selectedElementIds);
      updateActiveSlide((slide) => ({
        ...slide,
        elements: slide.elements.map((element) => {
          if (!selected.has(element.id)) return element;
          if (Boolean(element.style?.locked)) return element;
          const x = clamp(
            snap(element.box.x + dx),
            0,
            Math.max(0, deck.size.width - element.box.w),
          );
          const y = clamp(
            snap(element.box.y + dy),
            0,
            Math.max(0, deck.size.height - element.box.h),
          );
          return { ...element, box: { ...element.box, x, y } };
        }),
      }));
    },
    [deck, activeSlide, selectedElementIds, updateActiveSlide],
  );

  const alignSelected = useCallback(
    (mode: "left" | "center" | "right" | "top" | "middle" | "bottom") => {
      if (!deck || !activeSlide || selectedElementIds.length < 2) return;
      const selected = activeSlide.elements.filter((element) =>
        selectedElementIds.includes(element.id),
      );
      const xs = selected.map((item) => item.box.x);
      const ys = selected.map((item) => item.box.y);
      const rights = selected.map((item) => item.box.x + item.box.w);
      const bottoms = selected.map((item) => item.box.y + item.box.h);
      const targetLeft = Math.min(...xs);
      const targetRight = Math.max(...rights);
      const targetTop = Math.min(...ys);
      const targetBottom = Math.max(...bottoms);
      const centerX = (targetLeft + targetRight) / 2;
      const centerY = (targetTop + targetBottom) / 2;
      const selectedSet = new Set(selectedElementIds);
      updateActiveSlide((slide) => ({
        ...slide,
        elements: slide.elements.map((element) => {
          if (!selectedSet.has(element.id) || Boolean(element.style?.locked)) return element;
          let x = element.box.x;
          let y = element.box.y;
          if (mode === "left") x = targetLeft;
          if (mode === "center") x = centerX - element.box.w / 2;
          if (mode === "right") x = targetRight - element.box.w;
          if (mode === "top") y = targetTop;
          if (mode === "middle") y = centerY - element.box.h / 2;
          if (mode === "bottom") y = targetBottom - element.box.h;
          return {
            ...element,
            box: {
              ...element.box,
              x: clamp(snap(x), 0, Math.max(0, deck.size.width - element.box.w)),
              y: clamp(snap(y), 0, Math.max(0, deck.size.height - element.box.h)),
            },
          };
        }),
      }));
    },
    [deck, activeSlide, selectedElementIds, updateActiveSlide],
  );

  const distributeSelected = useCallback(
    (axis: "horizontal" | "vertical") => {
      if (!deck || !activeSlide || selectedElementIds.length < 3) return;
      const selected = activeSlide.elements
        .filter((element) => selectedElementIds.includes(element.id))
        .filter((element) => !Boolean(element.style?.locked))
        .sort((a, b) => (axis === "horizontal" ? a.box.x - b.box.x : a.box.y - b.box.y));
      if (selected.length < 3) return;

      const first = selected[0];
      const last = selected[selected.length - 1];
      const span =
        axis === "horizontal"
          ? last.box.x - first.box.x
          : last.box.y - first.box.y;
      const step = span / Math.max(1, selected.length - 1);

      const updates = new Map<string, number>();
      selected.forEach((element, index) => {
        updates.set(element.id, axis === "horizontal" ? first.box.x + step * index : first.box.y + step * index);
      });

      const selectedSet = new Set(selectedElementIds);
      updateActiveSlide((slide) => ({
        ...slide,
        elements: slide.elements.map((element) => {
          if (!selectedSet.has(element.id) || !updates.has(element.id)) return element;
          const value = updates.get(element.id) || 0;
          if (axis === "horizontal") {
            return {
              ...element,
              box: {
                ...element.box,
                x: clamp(snap(value), 0, Math.max(0, deck.size.width - element.box.w)),
              },
            };
          }
          return {
            ...element,
            box: {
              ...element.box,
              y: clamp(snap(value), 0, Math.max(0, deck.size.height - element.box.h)),
            },
          };
        }),
      }));
    },
    [deck, activeSlide, selectedElementIds, updateActiveSlide],
  );

  const adjustZIndex = useCallback(
    (toFront: boolean) => {
      if (!activeSlide || selectedElementIds.length === 0) return;
      const zValues = activeSlide.elements.map((element) => asNumber(element.style?.zIndex, 0));
      const minZ = Math.min(...zValues, 0);
      const maxZ = Math.max(...zValues, 0);
      const selectedSet = new Set(selectedElementIds);
      updateActiveSlide((slide) => ({
        ...slide,
        elements: slide.elements.map((element) => {
          if (!selectedSet.has(element.id)) return element;
          return {
            ...element,
            style: {
              ...element.style,
              zIndex: toFront ? maxZ + 1 : minZ - 1,
            },
          };
        }),
      }));
    },
    [activeSlide, selectedElementIds, updateActiveSlide],
  );

  const getPointerCanvasPoint = useCallback((clientX: number, clientY: number) => {
    const rect = stageSurfaceRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const scale = stageScaleRef.current || 1;
    const x = clamp((clientX - rect.left) / scale, 0, DEFAULT_SIZE.width);
    const y = clamp((clientY - rect.top) / scale, 0, DEFAULT_SIZE.height);
    return { x, y };
  }, []);

  const onWindowPointerMove = useCallback(
    (event: PointerEvent) => {
      const session = dragRef.current;
      if (!session || !deck) return;
      const dx = (event.clientX - session.startClientX) / stageScaleRef.current;
      const dy = (event.clientY - session.startClientY) / stageScaleRef.current;
      const selectedSet = new Set(session.selectedIds);

      updateActiveSlide((slide) => {
        const nextElements = slide.elements.map((element) => {
          if (!selectedSet.has(element.id)) return element;
          if (Boolean(element.style?.locked)) return element;
          const initial = session.initialBoxes[element.id];
          if (!initial) return element;

          if (session.mode === "move") {
            const nextX = clamp(
              snap(initial.x + dx),
              0,
              Math.max(0, deck.size.width - initial.w),
            );
            const nextY = clamp(
              snap(initial.y + dy),
              0,
              Math.max(0, deck.size.height - initial.h),
            );
            return {
              ...element,
              box: { ...element.box, x: nextX, y: nextY },
            };
          }

          if (session.mode === "resize" && element.id === session.elementId) {
            const nextW = clamp(
              snap(initial.w + dx),
              60,
              Math.max(60, deck.size.width - initial.x),
            );
            const nextH = clamp(
              snap(initial.h + dy),
              40,
              Math.max(40, deck.size.height - initial.y),
            );
            return {
              ...element,
              box: { ...element.box, w: nextW, h: nextH },
            };
          }

          if (session.mode === "rotate" && element.id === session.elementId && session.rotateCenter) {
            const point = getPointerCanvasPoint(event.clientX, event.clientY);
            if (!point) return element;
            const angle =
              (Math.atan2(point.y - session.rotateCenter.y, point.x - session.rotateCenter.x) *
                180) /
              Math.PI;
            return {
              ...element,
              box: { ...element.box, rot: Math.round(angle) },
            };
          }

          return element;
        });

        return { ...slide, elements: nextElements };
      });
    },
    [deck, getPointerCanvasPoint, updateActiveSlide],
  );

  const onWindowPointerUp = useCallback(function handlePointerUp() {
    dragRef.current = null;
    window.removeEventListener("pointermove", onWindowPointerMove);
    window.removeEventListener("pointerup", handlePointerUp);
  }, [onWindowPointerMove]);

  const startDrag = useCallback(
    (
      event: React.PointerEvent,
      element: SlideElement,
      mode: "move" | "resize" | "rotate",
      allowMultiSelect: boolean,
    ) => {
      event.preventDefault();
      event.stopPropagation();
      if (!activeSlide) return;
      if (Boolean(element.style?.locked)) return;

      const selected = allowMultiSelect
        ? Array.from(new Set([...selectedElementIds, element.id]))
        : [element.id];
      setSelectedElementIds(selected);

      const selectedSet = new Set(selected);
      const initialBoxes: Record<string, SlideElementBox> = {};
      for (const item of activeSlide.elements) {
        if (!selectedSet.has(item.id)) continue;
        initialBoxes[item.id] = { ...item.box };
      }

      const rotateCenter = {
        x: element.box.x + element.box.w / 2,
        y: element.box.y + element.box.h / 2,
      };

      dragRef.current = {
        mode,
        elementId: element.id,
        selectedIds: selected,
        startClientX: event.clientX,
        startClientY: event.clientY,
        initialBoxes,
        rotateCenter,
      };

      window.addEventListener("pointermove", onWindowPointerMove);
      window.addEventListener("pointerup", onWindowPointerUp);
    },
    [
      activeSlide,
      selectedElementIds,
      onWindowPointerMove,
      onWindowPointerUp,
      setSelectedElementIds,
    ],
  );

  useEffect(() => {
    return () => {
      window.removeEventListener("pointermove", onWindowPointerMove);
      window.removeEventListener("pointerup", onWindowPointerUp);
    };
  }, [onWindowPointerMove, onWindowPointerUp]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isInputLike(event.target)) return;
      const meta = event.metaKey || event.ctrlKey;
      const step = event.shiftKey ? 16 : 4;
      if (event.key === "Delete" || event.key === "Backspace") {
        if (selectedElementIds.length > 0) {
          event.preventDefault();
          removeSelectedElements();
        }
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        nudgeSelected(-step, 0);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        nudgeSelected(step, 0);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        nudgeSelected(0, -step);
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        nudgeSelected(0, step);
      } else if (meta && event.key.toLowerCase() === "d") {
        event.preventDefault();
        duplicateSelected();
      } else if (meta && event.key.toLowerCase() === "a" && activeSlide) {
        event.preventDefault();
        setSelectedElementIds(activeSlide.elements.map((element) => element.id));
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeSlide, duplicateSelected, nudgeSelected, removeSelectedElements, selectedElementIds.length]);

  useEffect(() => {
    const fetchTemplates = async () => {
      try {
        const response = await apiFetch(apiUrl("/api/v1/slide-pro/templates"));
        const payload = (await response.json()) as { templates?: SlideProTemplate[] };
        const list = payload.templates || [];
        setTemplates(list);
        if (list.length > 0 && !list.some((item) => item.id === selectedTemplateId)) {
          setSelectedTemplateId(list[0].id);
        }
      } catch (templateError) {
        console.error("Failed to load slide templates:", templateError);
      }
    };

    const fetchResearchOptions = async () => {
      try {
        const response = await apiFetch(apiUrl("/api/v1/slide-pro/research-options"));
        const payload = (await response.json()) as SlideProResearchOptionsResponse;

        const kbList = payload.knowledge_bases || [];
        const defaultKbs = payload.default_kb_names || [];
        const searchCfg = payload.search || {
          default_provider: DEFAULT_SEARCH_PROVIDER,
          providers: [],
          default_effort: DEFAULT_SEARCH_EFFORT,
          efforts: [],
        };

        setKnowledgeBaseOptions(kbList);
        setDefaultKbNames(defaultKbs);
        setSelectedKbNames((prev) => {
          const validPrev = prev.filter((name) => kbList.some((item) => item.name === name));
          if (validPrev.length > 0) return validPrev;

          const validDefaults = defaultKbs.filter((name) => kbList.some((item) => item.name === name));
          if (validDefaults.length > 0) return validDefaults;

          const optionDefaults = kbList.filter((item) => item.is_default).map((item) => item.name);
          if (optionDefaults.length > 0) return optionDefaults;

          return kbList[0] ? [kbList[0].name] : [];
        });

        const providers = searchCfg.providers || [];
        setSearchProviderOptions(providers);
        setDefaultSearchProvider(searchCfg.default_provider || DEFAULT_SEARCH_PROVIDER);
        setSearchProvider((prev) => {
          const valid = providers.some((item) => item.id === prev);
          if (valid) return prev;
          return searchCfg.default_provider || providers[0]?.id || DEFAULT_SEARCH_PROVIDER;
        });
        setSearchEffort((prev) => {
          if (prev === "fast" || prev === "medium" || prev === "high") return prev;
          return searchCfg.default_effort || DEFAULT_SEARCH_EFFORT;
        });
      } catch (researchOptionError) {
        console.error("Failed to load slide research options:", researchOptionError);
      }
    };

    const fetchNotebooks = async () => {
      try {
        const response = await apiFetch(apiUrl("/api/v1/notebook/list"));
        const payload = (await response.json()) as { notebooks?: NotebookSummary[] };
        const list = payload.notebooks || [];
        setNotebooks(list);
        if (!selectedNotebookId && list.length > 0) {
          setSelectedNotebookId(list[0].id);
        }
      } catch (notebookError) {
        console.error("Failed to load notebooks:", notebookError);
      }
    };

    void fetchTemplates();
    void fetchResearchOptions();
    void fetchNotebooks();
  }, [selectedNotebookId, selectedTemplateId]);

  useEffect(() => {
    if (!deck) return;
    if (activeSlideIndex > deck.slides.length - 1) {
      setActiveSlideIndex(Math.max(0, deck.slides.length - 1));
    }
  }, [deck, activeSlideIndex]);

  useEffect(() => {
    const container = stageContainerRef.current;
    if (!container) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const width = Math.max(320, entry.contentRect.width - 24);
      const height = Math.max(260, entry.contentRect.height - 24);
      setStageViewport({ width, height });
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  const setSingleElementBox = useCallback(
    (patch: Partial<SlideElementBox>) => {
      if (!deck || !selectedSingleElement) return;
      const prev = selectedSingleElement.box;
      const nextW = patch.w !== undefined ? patch.w : prev.w;
      const nextH = patch.h !== undefined ? patch.h : prev.h;
      const x = patch.x !== undefined ? patch.x : prev.x;
      const y = patch.y !== undefined ? patch.y : prev.y;
      patchElement(selectedSingleElement.id, (element) => ({
        ...element,
        box: {
          ...element.box,
          ...patch,
          x: clamp(snap(x), 0, Math.max(0, deck.size.width - nextW)),
          y: clamp(snap(y), 0, Math.max(0, deck.size.height - nextH)),
          w: clamp(snap(nextW), 60, deck.size.width),
          h: clamp(snap(nextH), 40, deck.size.height),
        },
      }));
    },
    [deck, patchElement, selectedSingleElement],
  );

  const setSingleElementStyle = useCallback(
    (patch: Record<string, string | number | boolean>) => {
      if (!selectedSingleElement) return;
      patchElement(selectedSingleElement.id, (element) => ({
        ...element,
        style: { ...element.style, ...patch },
      }));
    },
    [patchElement, selectedSingleElement],
  );

  const setSingleElementContent = useCallback(
    (content: string) => {
      if (!selectedSingleElement) return;
      patchElement(selectedSingleElement.id, (element) => {
        if (element.type === "bullets") {
          return { ...element, content: content.split("\n").map((line) => line.trim()).filter(Boolean) };
        }
        if (element.type === "table") {
          const rows = content
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean)
            .map((line) => line.split("|").map((cell) => cell.trim()));
          return {
            ...element,
            data: { ...element.data, rows },
          };
        }
        if (element.type === "chart") {
          const values = content
            .split(",")
            .map((part) => Number(part.trim()))
            .filter((value) => Number.isFinite(value));
          return {
            ...element,
            data: {
              ...element.data,
              labels: values.map((_, index) => `S${index + 1}`),
              series: [{ name: "Series", values }],
              grounded: values.length > 0,
            },
          };
        }
        return { ...element, content };
      });
    },
    [patchElement, selectedSingleElement],
  );

  const onStageBackgroundPointerDown = useCallback(() => {
    setSelectedElementIds([]);
  }, []);

  const sortedElements = useMemo(() => {
    if (!activeSlide) return [];
    return [...activeSlide.elements].sort(
      (a, b) => asNumber(a.style?.zIndex, 0) - asNumber(b.style?.zIndex, 0),
    );
  }, [activeSlide]);

  const renderElementBody = useCallback(
    (element: SlideElement, scale: number) => {
      const foreground = deck?.theme.palette.foreground || "#0F172A";
      const muted = deck?.theme.palette.muted || "#64748B";
      const color = asString(element.style?.color, foreground);
      const baseFontSize = asNumber(element.style?.fontSize, element.type === "text" ? 36 : 24);
      const textFit = asString(element.style?.textFit, "shrink");
      let resolvedFontSize = baseFontSize;
      if (
        textFit !== "none" &&
        (element.type === "text" || element.type === "bullets" || element.type === "equation")
      ) {
        let guard = 0;
        while (
          guard < 14 &&
          resolvedFontSize > 14 &&
          estimateTextOverflow({ ...element, style: { ...element.style, fontSize: resolvedFontSize } })
        ) {
          resolvedFontSize -= 1;
          guard += 1;
        }
      }
      const fontSize = resolvedFontSize * scale;
      const refs = Array.isArray(element.evidence_refs) ? element.evidence_refs.filter(Boolean) : [];
      const isTitle = isTitleElement(element);
      const bodyFont = deck ? previewFontFamily(deck, "body") : '"Aptos", "Segoe UI", Arial, sans-serif';
      const titleFont = deck ? previewFontFamily(deck, "title") : '"Aptos Display", "Segoe UI", Arial, sans-serif';
      const chosenFont = isTitle ? titleFont : bodyFont;

      if (element.type === "text" || element.type === "equation") {
        const lineHeight = resolveLineHeight(element);
        const wrappedText = resolveWrappedTextLines(element, resolvedFontSize);
        return (
          <div
            className="w-full h-full overflow-hidden whitespace-pre-line"
            style={{
              color,
              fontSize,
              fontWeight: asNumber(element.style?.fontWeight, 500),
              lineHeight,
              fontFamily: element.type === "equation" ? "Cambria Math, serif" : chosenFont,
            }}
          >
            {wrappedText.join("\n")}
            {refs.length > 0 && (
              <span className="ml-1 text-[10px] align-top opacity-80" style={{ color: muted }}>
                [{refs.join(", ")}]
              </span>
            )}
          </div>
        );
      }

      if (element.type === "bullets") {
        const lines = resolveWrappedBulletLines(element, resolvedFontSize);
        const lineHeight = resolveLineHeight(element);
        const bulletSpacingPx = (resolveBulletSpacingPt(element) * 96 * scale) / 72;
        const bulletIndentPx = (14 * 96 * scale) / 72;
        return (
          <div className="w-full h-full overflow-hidden" style={{ color, fontSize, lineHeight, fontFamily: bodyFont }}>
            <div className="w-full h-full overflow-hidden">
              {lines.map((line, index) => (
                <div
                  key={`${element.id}_${index}`}
                  className="flex items-start"
                  style={{ marginBottom: Math.max(1, bulletSpacingPx) }}
                >
                  <span
                    className="inline-block shrink-0"
                    style={{ width: Math.max(8, bulletIndentPx), paddingRight: Math.max(2, 4 * scale) }}
                  >
                    {line.bullet ? "•" : ""}
                  </span>
                  <span className="block break-words">{line.text}</span>
                </div>
              ))}
            </div>
            {refs.length > 0 && (
              <div className="text-[10px] mt-1 text-right opacity-80" style={{ color: muted }}>
                [{refs.join(", ")}]
              </div>
            )}
          </div>
        );
      }

      if (element.type === "shape") {
        return (
          <div
            className="w-full h-full flex items-center justify-center text-center px-3"
            style={{
              background: colorToCss(element.style?.fill, "#E2E8F0", element.style?.fillOpacity),
              borderColor: asString(element.style?.borderColor, "#94A3B8"),
              borderWidth: asNumber(element.style?.borderWidth, 1) * scale,
              borderRadius: asNumber(element.style?.cornerRadius, 14) * scale,
              color,
              fontSize: Math.max(12, fontSize - 2),
              fontFamily: bodyFont,
            }}
          >
            {toSingleText(element.content)}
          </div>
        );
      }

      if (element.type === "icon") {
        return (
          <div
            className="w-full h-full flex items-center justify-center"
            style={{ color, fontSize: Math.max(22, fontSize + 10), fontWeight: 700, fontFamily: titleFont }}
          >
            {toSingleText(element.content) || "★"}
          </div>
        );
      }

      if (element.type === "image") {
        const borderColor = asString(element.style?.borderColor, "#94A3B8");
        const borderWidth = asNumber(element.style?.borderWidth, 1) * scale;
        const cornerRadius = asNumber(element.style?.cornerRadius, 12) * scale;
        return (
          <div
            className="w-full h-full flex items-center justify-center overflow-hidden"
            style={{
              border: `${borderWidth}px solid ${borderColor}`,
              borderRadius: cornerRadius,
              background: colorToCss(element.style?.background, "#F8FAFC", element.style?.fillOpacity),
            }}
          >
            {element.src ? (
              <img src={element.src} alt="asset" className="w-full h-full object-cover" />
            ) : (
              <span
                className="text-center px-4"
                style={{ color: muted, fontSize: Math.max(10, fontSize - 6) }}
              >
                {asString(element.asset_hint, "Image placeholder")}
              </span>
            )}
          </div>
        );
      }

      if (element.type === "chart") {
        const grounded = hasGroundedChartData(element);
        const chartSvgData = buildChartSvgDataUrl(element, {
          accent: asString(element.style?.color, deck?.theme.palette.accent || "#0284C7"),
          foreground,
          muted,
          background: deck?.theme.palette.background || "#FFFFFF",
        });
        if (!grounded || !chartSvgData) {
          return (
            <div className="w-full h-full border border-slate-200 rounded-md p-3 flex items-center justify-center text-center">
              <span style={{ color: muted, fontSize: Math.max(10, fontSize - 6), fontFamily: bodyFont }}>
                Quantitative chart omitted: insufficient numeric evidence in sources.
              </span>
            </div>
          );
        }
        return (
          <div className="w-full h-full border border-slate-200 rounded-md p-2 flex flex-col">
            <img src={chartSvgData} alt="chart" className="w-full flex-1 object-contain" />
            {refs.length > 0 && (
              <div className="text-[10px] mt-1 text-right opacity-80" style={{ color: muted }}>
                [{refs.join(", ")}]
              </div>
            )}
          </div>
        );
      }

      const rows = Array.isArray(element.data?.rows)
        ? (element.data?.rows as Array<Array<unknown>>)
        : [];
      return (
        <div className="w-full h-full overflow-hidden border border-slate-200 rounded-md bg-white">
          <table className="w-full h-full text-xs border-collapse">
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`${element.id}_row_${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td
                      key={`${element.id}_cell_${rowIndex}_${cellIndex}`}
                      className="border border-slate-200 px-1 py-0.5"
                      style={{
                        color,
                        fontWeight: rowIndex === 0 ? 600 : 400,
                        fontSize: Math.max(10, fontSize - 8),
                        fontFamily: bodyFont,
                      }}
                    >
                      {String(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    },
    [deck],
  );

  return (
    <div className="h-screen p-4 flex flex-col gap-4 overflow-hidden">
      <div className="rounded-2xl border border-slate-200 bg-gradient-to-r from-sky-50 via-cyan-50 to-emerald-50 px-4 py-3 shadow-sm flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link
            href="/notebook"
            className="inline-flex items-center gap-1 text-xs text-slate-600 hover:text-slate-800"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            Notebook
          </Link>
          <div className="h-5 w-px bg-slate-300" />
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-cyan-700" />
            <h1 className="text-sm md:text-base font-semibold text-slate-900">Slide Generator Pro</h1>
            <span className="text-[11px] px-2 py-0.5 rounded-full bg-white/70 border border-cyan-200 text-cyan-700">
              Learn & Research
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={handleGenerate}
            disabled={loadingGenerate}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-cyan-600 text-white hover:bg-cyan-700 disabled:opacity-60"
          >
            {loadingGenerate ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />}
            Generate
          </button>
          <button
            onClick={handleClearWorkspace}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-300 bg-white hover:bg-slate-50"
            title="Clear planner inputs and generated deck"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Clear
          </button>
          <button
            onClick={runCritic}
            disabled={loadingCritic || !deck}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-300 bg-white hover:bg-slate-50 disabled:opacity-60"
          >
            {loadingCritic ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            Critic
          </button>
          <button
            onClick={handleExportJson}
            disabled={!deck}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-300 bg-white hover:bg-slate-50 disabled:opacity-60"
          >
            <FileJson className="w-3.5 h-3.5" />
            Export JSON
          </button>
          <button
            onClick={handleExportPptx}
            disabled={!deck || loadingExportPptx}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-300 bg-white hover:bg-slate-50 disabled:opacity-60"
          >
            {loadingExportPptx ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <FileDown className="w-3.5 h-3.5" />
            )}
            Export PPTX
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-[320px_minmax(0,1fr)_360px] gap-4">
        <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden flex flex-col">
          <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-800">Planner & Templates</h2>
            <button
              onClick={() => setShowNotebookImport(true)}
              className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border border-slate-200 hover:bg-slate-50"
            >
              <BookOpen className="w-3 h-3" />
              Import Notebook
            </button>
          </div>

          <div className="p-4 space-y-4 overflow-y-auto flex-1">
            <div>
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Title</label>
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm"
                placeholder="Presentation title"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              <div>
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Language</label>
                <select
                  value={language}
                  onChange={(event) => setLanguage(event.target.value as "vi" | "en")}
                  className="mt-1 w-full rounded-lg border border-slate-200 px-2 py-2 text-sm bg-white"
                >
                  <option value="vi">Vietnamese</option>
                  <option value="en">English</option>
                </select>
              </div>
              <div>
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Slides</label>
                <input
                  type="number"
                  min={3}
                  max={24}
                  value={slideCount}
                  onChange={(event) => setSlideCount(clamp(Number(event.target.value), 3, 24))}
                  className="mt-1 w-full rounded-lg border border-slate-200 px-2 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Retry / Slide
                </label>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={maxInstructionLoops}
                  onChange={(event) => setMaxInstructionLoops(clamp(Number(event.target.value), 1, 20))}
                  className="mt-1 w-full rounded-lg border border-slate-200 px-2 py-2 text-sm"
                />
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between gap-2">
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Source Material
                </label>
                <button
                  onClick={() => setShowNotebookImport(true)}
                  className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border border-slate-200 hover:bg-slate-50"
                >
                  <BookOpen className="w-3 h-3" />
                  Import Notebook
                </button>
              </div>
              <textarea
                value={sourceText}
                onChange={(event) => setSourceText(event.target.value)}
                rows={8}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm resize-none"
                placeholder="Paste notes, lesson materials, key facts..."
              />
              {importedRecords.length > 0 && (
                <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50/70 p-2">
                  <p className="text-[11px] text-slate-600">
                    Imported records: {importedRecords.length}
                  </p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {importedRecords.slice(0, 8).map((record) => (
                      <span
                        key={`${record.source_notebook_id || "nb"}:${record.id}`}
                        className="px-2 py-0.5 rounded-md bg-white border border-slate-200 text-[10px] text-slate-600"
                        title={record.title}
                      >
                        {record.title || "Untitled"} · {record.type}
                      </span>
                    ))}
                    {importedRecords.length > 8 && (
                      <span className="px-2 py-0.5 rounded-md bg-white border border-slate-200 text-[10px] text-slate-500">
                        +{importedRecords.length - 8} more
                      </span>
                    )}
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <button
                      onClick={() => setSourceText(recordsToSourceText(importedRecords))}
                      className="text-[11px] px-2 py-1 rounded-md border border-slate-200 bg-white hover:bg-slate-100"
                    >
                      Rebuild from imports
                    </button>
                    <button
                      onClick={() => setImportedRecords([])}
                      className="text-[11px] px-2 py-1 rounded-md border border-slate-200 bg-white hover:bg-slate-100"
                    >
                      Clear import list
                    </button>
                  </div>
                </div>
              )}
            </div>

            <div>
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Additional Instructions
              </label>
              <textarea
                value={instructions}
                onChange={(event) => setInstructions(event.target.value)}
                rows={4}
                className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm resize-none"
                placeholder="Audience, pacing, style constraints..."
              />
            </div>

            <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3 space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                Research Agent
              </p>
              <label className="flex items-center gap-2 text-xs text-slate-700">
                <input
                  type="checkbox"
                  checked={enableKbResearch}
                  onChange={(event) => setEnableKbResearch(event.target.checked)}
                  className="rounded border-slate-300"
                />
                Always run Knowledge Base retrieval
              </label>
              {enableKbResearch && (
                <div className="rounded-lg border border-slate-200 bg-white p-2 space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-[11px] text-slate-600">
                      Selected KBs: {selectedKbNames.length}
                    </p>
                    <div className="flex items-center gap-1.5">
                      <button
                        onClick={() => setSelectedKbNames(knowledgeBaseOptions.map((item) => item.name))}
                        disabled={knowledgeBaseOptions.length === 0}
                        className="text-[10px] px-2 py-1 rounded border border-slate-200 bg-white hover:bg-slate-50 disabled:opacity-50"
                      >
                        Select all
                      </button>
                      <button
                        onClick={() => setSelectedKbNames([])}
                        className="text-[10px] px-2 py-1 rounded border border-slate-200 bg-white hover:bg-slate-50"
                      >
                        Clear
                      </button>
                    </div>
                  </div>

                  {knowledgeBaseOptions.length === 0 ? (
                    <p className="text-[11px] text-slate-500">
                      No knowledge base found.
                    </p>
                  ) : (
                    <div className="max-h-40 overflow-y-auto space-y-1.5 pr-1">
                      {knowledgeBaseOptions.map((kb) => {
                        const checked = selectedKbNames.includes(kb.name);
                        return (
                          <label
                            key={kb.name}
                            className="block rounded-md border border-slate-200 px-2 py-1.5 text-[11px] text-slate-700"
                          >
                            <div className="flex items-start gap-2">
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => toggleKnowledgeBase(kb.name)}
                                className="mt-0.5 rounded border-slate-300"
                              />
                              <div className="min-w-0">
                                <p className="font-semibold truncate">
                                  {kb.name}
                                  {kb.is_default ? " (default)" : ""}
                                </p>
                                <div className="mt-0.5 flex flex-wrap gap-1">
                                  <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">
                                    rag: {kb.rag_provider}
                                  </span>
                                  <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">
                                    mode: {kb.search_mode}
                                  </span>
                                  <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-600">
                                    profile: {kb.retrieval_profile}
                                  </span>
                                </div>
                              </div>
                            </div>
                          </label>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              <label className="flex items-center gap-2 text-xs text-slate-700">
                <input
                  type="checkbox"
                  checked={enableWebSearch}
                  onChange={(event) => setEnableWebSearch(event.target.checked)}
                  className="rounded border-slate-300"
                />
                Always run Web Search
              </label>
              {enableWebSearch && (
                <div className="rounded-lg border border-slate-200 bg-white p-2 space-y-2">
                  <div className="grid grid-cols-2 gap-2">
                    <label className="text-[11px] text-slate-600">
                      Search engine
                      <select
                        value={searchProvider}
                        onChange={(event) => setSearchProvider(event.target.value)}
                        className="mt-1 w-full rounded border border-slate-200 bg-white px-2 py-1.5 text-sm"
                      >
                        {searchProviderOptions.length === 0 ? (
                          <option value={searchProvider || DEFAULT_SEARCH_PROVIDER}>
                            {searchProvider || DEFAULT_SEARCH_PROVIDER}
                          </option>
                        ) : (
                          searchProviderOptions.map((provider) => (
                            <option key={provider.id} value={provider.id}>
                              {provider.name || provider.display_name || provider.id}
                            </option>
                          ))
                        )}
                      </select>
                    </label>
                    <label className="text-[11px] text-slate-600">
                      Effort
                      <select
                        value={searchEffort}
                        onChange={(event) => setSearchEffort(event.target.value as SlideProResearchEffort)}
                        className="mt-1 w-full rounded border border-slate-200 bg-white px-2 py-1.5 text-sm"
                      >
                        <option value="fast">Fast</option>
                        <option value="medium">Medium</option>
                        <option value="high">High</option>
                      </select>
                    </label>
                  </div>
                  {currentSearchProviderOption?.description && (
                    <p className="text-[11px] text-slate-500">
                      {currentSearchProviderOption.description}
                    </p>
                  )}
                </div>
              )}
            </div>

            <div>
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Template Packs
              </label>
              <div className="mt-2 space-y-2">
                {templates.map((template) => {
                  const isActive = template.id === selectedTemplateId;
                  return (
                    <button
                      key={template.id}
                      onClick={() => setSelectedTemplateId(template.id)}
                      className={`w-full text-left rounded-xl border p-3 transition ${
                        isActive
                          ? "border-cyan-400 bg-cyan-50"
                          : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <p className="text-sm font-semibold text-slate-800">{template.name}</p>
                          <p className="text-xs text-slate-500 mt-0.5">{template.description}</p>
                        </div>
                        {isActive && <ChevronRight className="w-4 h-4 text-cyan-700 mt-0.5" />}
                      </div>
                      <div className="flex gap-1 mt-2">
                        {[
                          template.theme.palette.background,
                          template.theme.palette.accent,
                          template.theme.palette.foreground,
                        ].map((color) => (
                          <span
                            key={color}
                            className="w-4 h-4 rounded-full border border-white/70 shadow-sm"
                            style={{ backgroundColor: color }}
                          />
                        ))}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {deck && (
              <div>
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Slide Thumbnails
                </label>
                <div className="mt-2 space-y-2">
                  {deck.slides.map((slide, index) => {
                    const hasIssue = (issueMap.get(slide.id) || []).length > 0;
                    return (
                      <button
                        key={slide.id}
                        onClick={() => {
                          setActiveSlideIndex(index);
                          setSelectedElementIds([]);
                        }}
                        title={slide.title}
                        className={`w-full text-left rounded-xl border px-3 py-2 ${
                          activeSlideIndex === index
                            ? "border-cyan-400 bg-cyan-50"
                            : "border-slate-200 hover:bg-slate-50"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span
                            className="text-xs font-semibold text-slate-700"
                            style={{
                              display: "-webkit-box",
                              WebkitLineClamp: 2,
                              WebkitBoxOrient: "vertical",
                              overflow: "hidden",
                            }}
                          >
                            {index + 1}. {slide.title}
                          </span>
                          {hasIssue && <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />}
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden flex flex-col min-h-0">
          <div className="px-3 py-2 border-b border-slate-100 flex flex-wrap items-center gap-2">
            <div className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-slate-200 bg-slate-50">
              <MousePointer2 className="w-3.5 h-3.5 text-slate-600" />
              <span className="text-[11px] font-semibold text-slate-600">Editable Canvas</span>
            </div>

            {ELEMENT_TYPES.map((item) => (
              <button
                key={item.type}
                onClick={() => addElement(item.type)}
                disabled={!deck}
                className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] rounded-md border border-slate-200 hover:bg-slate-50 disabled:opacity-50"
              >
                <item.icon className="w-3.5 h-3.5" />
                {item.label}
              </button>
            ))}

            <div className="ml-auto flex items-center gap-1">
              <button
                onClick={() => alignSelected("left")}
                disabled={selectedElementIds.length < 2}
                className="p-1.5 rounded border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
                title="Align left"
              >
                <AlignHorizontalJustifyStart className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => alignSelected("center")}
                disabled={selectedElementIds.length < 2}
                className="p-1.5 rounded border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
                title="Align center"
              >
                <AlignHorizontalJustifyCenter className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => alignSelected("right")}
                disabled={selectedElementIds.length < 2}
                className="p-1.5 rounded border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
                title="Align right"
              >
                <AlignHorizontalJustifyEnd className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => alignSelected("top")}
                disabled={selectedElementIds.length < 2}
                className="p-1.5 rounded border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
                title="Align top"
              >
                <AlignVerticalJustifyStart className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => alignSelected("middle")}
                disabled={selectedElementIds.length < 2}
                className="p-1.5 rounded border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
                title="Align middle"
              >
                <AlignVerticalJustifyCenter className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => alignSelected("bottom")}
                disabled={selectedElementIds.length < 2}
                className="p-1.5 rounded border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
                title="Align bottom"
              >
                <AlignVerticalJustifyEnd className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => distributeSelected("horizontal")}
                disabled={selectedElementIds.length < 3}
                className="p-1.5 rounded border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
                title="Distribute horizontal"
              >
                <AlignCenter className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => distributeSelected("vertical")}
                disabled={selectedElementIds.length < 3}
                className="p-1.5 rounded border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
                title="Distribute vertical"
              >
                <AlignCenter className="w-3.5 h-3.5 rotate-90" />
              </button>
            </div>
          </div>

          <div ref={stageContainerRef} className="flex-1 min-h-0 p-3 bg-slate-100">
            {!deck || !activeSlide ? (
              <div className="h-full rounded-xl border border-dashed border-slate-300 bg-white flex items-center justify-center text-slate-500 text-sm">
                Generate a deck to start editing.
              </div>
            ) : (
              <div className="w-full h-full flex items-center justify-center">
                <div
                  ref={stageSurfaceRef}
                  className="relative shadow-xl border border-slate-300 overflow-hidden select-none"
                  style={{
                    width: `${deck.size.width * stageScale}px`,
                    height: `${deck.size.height * stageScale}px`,
                    background: deck.theme.palette.background,
                  }}
                  onPointerDown={onStageBackgroundPointerDown}
                >
                  <div
                    className="absolute inset-0 opacity-[0.08] pointer-events-none"
                    style={{
                      backgroundImage:
                        "linear-gradient(to right, #94a3b8 1px, transparent 1px), linear-gradient(to bottom, #94a3b8 1px, transparent 1px)",
                      backgroundSize: `${GRID * stageScale}px ${GRID * stageScale}px`,
                    }}
                  />

                  {sortedElements.map((element) => {
                    const isSelected = selectedElementIds.includes(element.id);
                    const locked = Boolean(element.style?.locked);
                    const hidden = Boolean(element.style?.hidden);
                    const hasOverflow = estimateTextOverflow(element);
                    const borderClass = isSelected
                      ? "ring-2 ring-cyan-500 ring-offset-0"
                      : "ring-0";
                    const left = element.box.x * stageScale;
                    const top = element.box.y * stageScale;
                    const width = element.box.w * stageScale;
                    const height = element.box.h * stageScale;
                    const zIndex = asNumber(element.style?.zIndex, 0) + 100;

                    return (
                      <div
                        key={element.id}
                        className={`absolute ${borderClass} rounded-sm`}
                        style={{
                          left,
                          top,
                          width,
                          height,
                          zIndex,
                          transform: `rotate(${element.box.rot}deg)`,
                          transformOrigin: "center center",
                          opacity: hidden ? 0.2 : 1,
                          cursor: locked ? "not-allowed" : "move",
                          pointerEvents: hidden ? "none" : "auto",
                        }}
                        onPointerDown={(event) =>
                          startDrag(event, element, "move", Boolean(event.shiftKey))
                        }
                        onClick={(event) => {
                          event.stopPropagation();
                          if (event.shiftKey) {
                            setSelectedElementIds((prev) =>
                              prev.includes(element.id)
                                ? prev.filter((id) => id !== element.id)
                                : [...prev, element.id],
                            );
                          } else {
                            setSelectedElementIds([element.id]);
                          }
                        }}
                      >
                        {renderElementBody(element, stageScale)}
                        {hasOverflow && (
                          <div className="absolute -top-4 right-0 text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 border border-amber-300">
                            overflow
                          </div>
                        )}
                        {isSelected && !locked && (
                          <>
                            <button
                              onPointerDown={(event) => startDrag(event, element, "resize", false)}
                              className="absolute -right-1 -bottom-1 w-3.5 h-3.5 rounded-full bg-cyan-600 border border-white"
                              title="Resize"
                            />
                            <button
                              onPointerDown={(event) => startDrag(event, element, "rotate", false)}
                              className="absolute left-1/2 -translate-x-1/2 -top-4 w-3.5 h-3.5 rounded-full bg-amber-500 border border-white"
                              title="Rotate"
                            />
                          </>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          <div className="px-3 py-2 border-t border-slate-100 bg-white text-[11px] text-slate-500 flex flex-wrap items-center gap-4">
            <span>Keyboard: `Del` remove, arrows nudge, `Ctrl/Cmd + D` duplicate, `Ctrl/Cmd + A` select all.</span>
            <span>Grid snap: {GRID}px</span>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden flex flex-col">
          <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-800">Inspector & Publish</h2>
            <div className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded border border-slate-200 bg-slate-50">
              <Layers className="w-3.5 h-3.5" />
              {selectedElementIds.length} selected
            </div>
          </div>

          <div className="p-4 space-y-4 overflow-y-auto flex-1">
            {currentTemplate && (
              <div className="rounded-xl border border-slate-200 p-3">
                <p className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Active Style</p>
                <p className="text-sm font-semibold text-slate-800 mt-1">{currentTemplate.name}</p>
                <p className="text-xs text-slate-500">{currentTemplate.description}</p>
                <div className="mt-2 text-[11px] text-slate-500">
                  Fonts: {currentTemplate.theme.fonts.title} / {currentTemplate.theme.fonts.body}
                </div>
              </div>
            )}

            {selectedSingleElement ? (
              <div className="rounded-xl border border-slate-200 p-3 space-y-3">
                <p className="text-xs font-semibold text-slate-600 uppercase tracking-wide">
                  Selected Element
                </p>
                <div className="grid grid-cols-2 gap-2">
                  <label className="text-xs text-slate-500">
                    X
                    <input
                      type="number"
                      value={Math.round(selectedSingleElement.box.x)}
                      onChange={(event) => setSingleElementBox({ x: Number(event.target.value) })}
                      className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm"
                    />
                  </label>
                  <label className="text-xs text-slate-500">
                    Y
                    <input
                      type="number"
                      value={Math.round(selectedSingleElement.box.y)}
                      onChange={(event) => setSingleElementBox({ y: Number(event.target.value) })}
                      className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm"
                    />
                  </label>
                  <label className="text-xs text-slate-500">
                    W
                    <input
                      type="number"
                      value={Math.round(selectedSingleElement.box.w)}
                      onChange={(event) => setSingleElementBox({ w: Number(event.target.value) })}
                      className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm"
                    />
                  </label>
                  <label className="text-xs text-slate-500">
                    H
                    <input
                      type="number"
                      value={Math.round(selectedSingleElement.box.h)}
                      onChange={(event) => setSingleElementBox({ h: Number(event.target.value) })}
                      className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm"
                    />
                  </label>
                </div>

                <label className="text-xs text-slate-500 block">
                  Rotation
                  <input
                    type="number"
                    value={Math.round(selectedSingleElement.box.rot)}
                    onChange={(event) => setSingleElementBox({ rot: Number(event.target.value) })}
                    className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm"
                  />
                </label>

                <div className="grid grid-cols-2 gap-2">
                  <label className="text-xs text-slate-500">
                    Font Size
                    <input
                      type="number"
                      value={asNumber(selectedSingleElement.style?.fontSize, 24)}
                      onChange={(event) =>
                        setSingleElementStyle({ fontSize: clamp(Number(event.target.value), 10, 96) })
                      }
                      className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm"
                    />
                  </label>
                  <label className="text-xs text-slate-500">
                    Color
                    <input
                      value={asString(selectedSingleElement.style?.color, "#0F172A")}
                      onChange={(event) => setSingleElementStyle({ color: event.target.value })}
                      className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm"
                    />
                  </label>
                </div>

                <label className="text-xs text-slate-500 block">
                  Content
                  <textarea
                    value={
                      selectedSingleElement.type === "bullets"
                        ? toLineArray(selectedSingleElement.content).join("\n")
                        : selectedSingleElement.type === "table"
                          ? (Array.isArray(selectedSingleElement.data?.rows)
                              ? (selectedSingleElement.data?.rows as Array<Array<unknown>>)
                                  .map((row) => row.map((cell) => String(cell)).join(" | "))
                                  .join("\n")
                              : "")
                          : selectedSingleElement.type === "chart"
                            ? (Array.isArray(selectedSingleElement.data?.series) &&
                              Array.isArray(
                                (selectedSingleElement.data?.series as Array<Record<string, unknown>>)[0]
                                  ?.values,
                              )
                                ? (
                                    (selectedSingleElement.data?.series as Array<Record<string, unknown>>)[0]
                                      .values as unknown[]
                                  ).join(", ")
                                : "")
                            : toSingleText(selectedSingleElement.content)
                    }
                    onChange={(event) => setSingleElementContent(event.target.value)}
                    rows={selectedSingleElement.type === "table" ? 5 : 4}
                    className="mt-1 w-full rounded border border-slate-200 px-2 py-2 text-sm resize-none"
                  />
                </label>

                {selectedSingleElement.type === "image" && (
                  <label className="text-xs text-slate-500 block">
                    Image URL or data URL
                    <input
                      value={asString(selectedSingleElement.src, "")}
                      onChange={(event) =>
                        patchElement(selectedSingleElement.id, (element) => ({
                          ...element,
                          src: event.target.value,
                        }))
                      }
                      className="mt-1 w-full rounded border border-slate-200 px-2 py-1.5 text-sm"
                    />
                  </label>
                )}

                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={() => setSingleElementStyle({ locked: !Boolean(selectedSingleElement.style?.locked) })}
                    className="inline-flex items-center justify-center gap-1.5 text-xs px-2 py-1.5 rounded-md border border-slate-200 hover:bg-slate-50"
                  >
                    {Boolean(selectedSingleElement.style?.locked) ? (
                      <>
                        <Unlock className="w-3.5 h-3.5" />
                        Unlock
                      </>
                    ) : (
                      <>
                        <Lock className="w-3.5 h-3.5" />
                        Lock
                      </>
                    )}
                  </button>
                  <button
                    onClick={() => setSingleElementStyle({ hidden: !Boolean(selectedSingleElement.style?.hidden) })}
                    className="inline-flex items-center justify-center gap-1.5 text-xs px-2 py-1.5 rounded-md border border-slate-200 hover:bg-slate-50"
                  >
                    {Boolean(selectedSingleElement.style?.hidden) ? (
                      <>
                        <Eye className="w-3.5 h-3.5" />
                        Show
                      </>
                    ) : (
                      <>
                        <EyeOff className="w-3.5 h-3.5" />
                        Hide
                      </>
                    )}
                  </button>
                  <button
                    onClick={() => adjustZIndex(true)}
                    className="inline-flex items-center justify-center gap-1.5 text-xs px-2 py-1.5 rounded-md border border-slate-200 hover:bg-slate-50"
                  >
                    <BringToFront className="w-3.5 h-3.5" />
                    Front
                  </button>
                  <button
                    onClick={() => adjustZIndex(false)}
                    className="inline-flex items-center justify-center gap-1.5 text-xs px-2 py-1.5 rounded-md border border-slate-200 hover:bg-slate-50"
                  >
                    <Minus className="w-3.5 h-3.5" />
                    Back
                  </button>
                </div>

                <button
                  onClick={removeSelectedElements}
                  className="w-full inline-flex items-center justify-center gap-1.5 text-xs px-2 py-2 rounded-md border border-red-200 bg-red-50 text-red-700 hover:bg-red-100"
                >
                  Remove Element
                </button>
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-slate-300 p-4 text-sm text-slate-500">
                Select one element to edit detailed properties.
              </div>
            )}

            <div className="rounded-xl border border-slate-200 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Critic</p>
                <button
                  onClick={applySuggestedPatches}
                  disabled={suggestedPatches.length === 0}
                  className="text-[11px] px-2 py-1 rounded border border-slate-200 hover:bg-slate-50 disabled:opacity-40"
                >
                  Apply Suggestions
                </button>
              </div>
              {criticIssues.length === 0 ? (
                <p className="text-xs text-emerald-700">No major critic issues.</p>
              ) : (
                <div className="space-y-2">
                  {criticIssues.map((issue) => (
                    <div key={issue.slide_id} className="text-xs rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5">
                      <p className="font-semibold text-amber-800">{issue.slide_id}</p>
                      {issue.issues.map((item) => (
                        <p key={`${issue.slide_id}_${item}`} className="text-amber-700">
                          - {item}
                        </p>
                      ))}
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="rounded-xl border border-slate-200 p-3 space-y-2">
              <p className="text-xs font-semibold text-slate-600 uppercase tracking-wide">
                Save to Notebook
              </p>
              <select
                value={selectedNotebookId}
                onChange={(event) => setSelectedNotebookId(event.target.value)}
                className="w-full rounded border border-slate-200 px-2 py-2 text-sm bg-white"
              >
                {notebooks.map((notebook) => (
                  <option key={notebook.id} value={notebook.id}>
                    {notebook.name} ({notebook.record_count})
                  </option>
                ))}
              </select>
              <button
                onClick={handleSaveToNotebook}
                disabled={!deck || !selectedNotebookId || loadingSaveNotebook}
                className="w-full inline-flex items-center justify-center gap-1.5 text-sm font-semibold px-3 py-2 rounded-md bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-60"
              >
                {loadingSaveNotebook ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Save className="w-4 h-4" />
                )}
                Save Notebook Record
              </button>
            </div>

            <div className="rounded-xl border border-slate-200 p-3">
              <p className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">
                Artifacts
              </p>
              {artifacts.length === 0 ? (
                <p className="text-xs text-slate-500">No uploaded artifacts yet.</p>
              ) : (
                <div className="space-y-1.5">
                  {artifacts.map((artifact) => (
                    <a
                      key={`${artifact.url}:${artifact.uploaded_at}`}
                      href={apiUrl(artifact.url)}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs flex items-center justify-between gap-2 rounded-md border border-slate-200 px-2 py-1.5 hover:bg-slate-50"
                    >
                      <span className="truncate">{artifact.file_name}</span>
                      <Download className="w-3.5 h-3.5 text-slate-500" />
                    </a>
                  ))}
                </div>
              )}
              {runId && (
                <p className="text-[11px] text-slate-400 mt-2">
                  Run ID: {runId}
                  {artifactBaseUrl ? ` • ${artifactBaseUrl}` : ""}
                </p>
              )}
            </div>

            {researchTrace && (
              <div className="rounded-xl border border-slate-200 p-3 space-y-2">
                <p className="text-xs font-semibold text-slate-600 uppercase tracking-wide">
                  Research Trace
                </p>
                <p className="text-xs text-slate-600">
                  KB: {researchTrace.enabled_kb ? "on" : "off"} • Web: {researchTrace.enabled_search ? "on" : "off"}
                </p>
                {researchTrace.web_run && (
                  <p className="text-xs text-slate-600">
                    Web: {researchTrace.web_run.provider || "n/a"} ({researchTrace.web_run.effort || "medium"}) •{" "}
                    {researchTrace.web_run.query_count || 1} queries • {researchTrace.web_run.citation_count || 0} refs •{" "}
                    {researchTrace.web_run.latency_ms || 0} ms
                  </p>
                )}
                {Array.isArray(researchTrace.queries) && researchTrace.queries.length > 0 && (
                  <p className="text-xs text-slate-500">
                    Queries: {researchTrace.queries.slice(0, 3).join(" | ")}
                  </p>
                )}
                {(researchTrace.kb_runs || []).map((run, idx) => (
                  <p key={`${run.kb_name || "kb"}_${idx}`} className="text-xs text-slate-600">
                    {run.kb_name}: {run.mode || "hybrid"} / {run.retrieval_profile || "standard"} •{" "}
                    {run.citation_count || 0} refs • {run.latency_ms || 0} ms
                  </p>
                ))}
              </div>
            )}

            <div className="rounded-xl border border-slate-200 p-3 space-y-2">
              <p className="text-xs font-semibold text-slate-600 uppercase tracking-wide">
                Evidence Coverage
              </p>
              {activeSlideMissingCitationClaims.length > 0 && (
                <div className="rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5">
                  <p className="text-xs font-semibold text-amber-700">Claims missing citation refs</p>
                  {activeSlideMissingCitationClaims.map((line) => (
                    <p key={line} className="text-xs text-amber-700">
                      - {line}
                    </p>
                  ))}
                </div>
              )}
              {!activeSlide || activeSlideEvidence.length === 0 ? (
                <p className="text-xs text-slate-500">No evidence refs attached to this slide.</p>
              ) : (
                <div className="space-y-1.5">
                  {activeSlideEvidence.map((item) => (
                    <div key={`${item.id}:${item.short_ref}`} className="text-xs rounded-md border border-slate-200 px-2 py-1.5">
                      <p className="font-semibold text-slate-700">
                        [{item.id}] {item.short_ref || item.title}
                      </p>
                      <p className="text-slate-500">
                        {item.source_type === "kb"
                          ? `${item.kb_name || "KB"} • ${item.doc_name || "document"}`
                          : item.source || "web"}
                      </p>
                      {item.url && (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-cyan-700 hover:underline break-all"
                        >
                          {item.url}
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {instructionReport && (
              <div className="rounded-xl border border-slate-200 p-3 space-y-1.5">
                <p className="text-xs font-semibold text-slate-600 uppercase tracking-wide">
                  Instruction Report
                </p>
                <p className="text-xs text-slate-600">
                  Major unresolved: {instructionReport.unresolved_major.length} • Minor unresolved:{" "}
                  {instructionReport.unresolved_minor.length}
                </p>
                {instructionReport.unresolved_major.slice(0, 6).map((item) => (
                  <p key={`major_${item.slide_id}`} className="text-xs text-amber-700">
                    {item.slide_id}: {item.reasons.join(", ")}
                  </p>
                ))}
              </div>
            )}

            {qualityChecks.length > 0 && (
              <div className="rounded-xl border border-slate-200 p-3">
                <p className="text-xs font-semibold text-slate-600 uppercase tracking-wide mb-2">
                  Quality Checks
                </p>
                <div className="space-y-1.5">
                  {qualityChecks.map((check) => (
                    <div
                      key={check.name}
                      className={`text-xs px-2 py-1.5 rounded-md border ${
                        check.status === "pass"
                          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                          : "border-amber-200 bg-amber-50 text-amber-700"
                      }`}
                    >
                      <p className="font-semibold">{check.name}</p>
                      <p>{check.detail}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {warnings.length > 0 && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-3">
                <p className="text-xs font-semibold text-amber-800 uppercase tracking-wide mb-1">
                  Warnings
                </p>
                {warnings.map((warning) => (
                  <p key={warning} className="text-xs text-amber-700">
                    - {warning}
                  </p>
                ))}
              </div>
            )}
          </div>

          <div className="p-3 border-t border-slate-100">
            {notice && (
              <p className="text-xs text-emerald-700 border border-emerald-200 bg-emerald-50 rounded px-2 py-1.5 mb-2">
                {notice}
              </p>
            )}
            {error && (
              <p className="text-xs text-red-700 border border-red-200 bg-red-50 rounded px-2 py-1.5">
                {error}
              </p>
            )}
          </div>
        </div>
      </div>

      <NotebookImportModal
        isOpen={showNotebookImport}
        onClose={() => setShowNotebookImport(false)}
        onImport={(content, records) => {
          const normalizedRecords = records.map((record) => normalizeImportedRecord(record));
          const importedText = content.trim() ? content.trim() : recordsToSourceText(normalizedRecords);
          if (importedText) {
            setSourceText((prev) => (prev.trim() ? `${prev}\n\n${importedText}` : importedText));
          }
          setImportedRecords((prev) => mergeImportedRecords(prev, normalizedRecords));
        }}
        title="Import Notebook Records into Slide Pro"
      />
    </div>
  );
}
