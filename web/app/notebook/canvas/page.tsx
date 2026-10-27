"use client";
import { apiFetch } from '@/lib/api';

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Check,
  Loader2,
  MousePointer2,
  Palette,
  PenLine,
  Plus,
  Save,
  ScanLine,
  Square,
  Eraser,
  Type,
  Sigma,
  Undo2,
  Redo2,
  Move,
  LassoSelect,
  SquareDashedMousePointer,
  Trash2,
} from "lucide-react";
import katex from "katex";
import "katex/dist/katex.min.css";

import { apiUrl } from "@/lib/api";

export const dynamic = "force-dynamic";

type ToolType =
  | "hand"
  | "pen"
  | "highlighter"
  | "eraser"
  | "rect"
  | "text"
  | "text_box"
  | "equation"
  | "select_rect"
  | "select_lasso";

interface Point {
  x: number;
  y: number;
  t: number;
}

interface Stroke {
  id: string;
  tool: ToolType;
  color: string;
  width: number;
  points: Point[];
  layer_id: string;
  text?: string;
}

interface OverlayTextStyle {
  fontFamily: string;
  fontSize: number;
  color: string;
  bold: boolean;
  italic: boolean;
  underline: boolean;
  strike: boolean;
  highlight: boolean;
}

type TextBooleanKey = "bold" | "italic" | "underline" | "strike" | "highlight";

interface CanvasOverlay {
  id: string;
  type: "text" | "equation";
  x: number;
  y: number;
  w: number;
  h: number;
  text: string;
  style: OverlayTextStyle;
}

interface CanvasPage {
  page_index: number;
  strokes: Stroke[];
  overlays: CanvasOverlay[];
  dirty_regions: Array<{ x: number; y: number; w: number; h: number }>;
}

interface NotebookSummary {
  id: string;
  name: string;
  record_count: number;
}

interface ReviewIssue {
  block_id: string;
  page_index: number;
  reason: string;
  confidence: number;
  suggested_text: string;
}

interface StructuredBlock {
  id: string;
  page_index: number;
  normalized_text: string;
  block_type: "heading" | "paragraph" | "equation" | "diagram" | "shape-note";
}

interface SelectionRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface SelectionDraft {
  kind: "rect" | "lasso";
  points: Point[];
}

interface DragState {
  active: boolean;
  startX: number;
  startY: number;
  baseStrokes: Stroke[];
}

interface OverlayDragState {
  overlayId: string;
  startClientX: number;
  startClientY: number;
  originX: number;
  originY: number;
}

interface OverlayResizeState {
  overlayId: string;
  startClientX: number;
  startClientY: number;
  originX: number;
  originY: number;
  originW: number;
  originH: number;
}

interface PanState {
  startClientX: number;
  startClientY: number;
  scrollLeft: number;
  scrollTop: number;
}

interface OcrDiagnostic {
  page_index: number;
  provider: string;
  api_key_configured: boolean;
  success: boolean;
  status_code?: number | null;
  used_fallback?: boolean;
  message?: string;
}

const CANVAS_WIDTH = 1600;
const CANVAS_HEIGHT = 900;
const COLORS = ["#0F172A", "#2563EB", "#7C3AED", "#DC2626", "#059669", "#D97706"];
const TEXT_FONTS = ["Arial", "Times New Roman", "Calibri", "Cambria", "Georgia", "Verdana"];
const DEFAULT_TEXT_STYLE: OverlayTextStyle = {
  fontFamily: "Calibri",
  fontSize: 28,
  color: "#0F172A",
  bold: false,
  italic: false,
  underline: false,
  strike: false,
  highlight: false,
};

function uid(prefix: string) {
  return `${prefix}_${Math.random().toString(36).slice(2, 8)}`;
}

function cloneStrokes(strokes: Stroke[]): Stroke[] {
  return strokes.map((stroke) => ({
    ...stroke,
    points: stroke.points.map((point) => ({ ...point })),
  }));
}

function strokeBounds(stroke: Stroke): SelectionRect | null {
  if (stroke.tool === "text" && stroke.points[0]) {
    const anchor = stroke.points[0];
    const text = stroke.text || "";
    const width = Math.max(12, text.length * Math.max(stroke.width * 0.55, 7));
    const height = Math.max(18, stroke.width * 1.35);
    return { x: anchor.x, y: anchor.y - height, w: width, h: height };
  }
  if (!stroke.points.length) return null;
  const xs = stroke.points.map((point) => point.x);
  const ys = stroke.points.map((point) => point.y);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const maxX = Math.max(...xs);
  const maxY = Math.max(...ys);
  const pad = Math.max(2, stroke.width * 0.5);
  return {
    x: minX - pad,
    y: minY - pad,
    w: maxX - minX + pad * 2,
    h: maxY - minY + pad * 2,
  };
}

function rectContainsPoint(rect: SelectionRect, x: number, y: number): boolean {
  return x >= rect.x && x <= rect.x + rect.w && y >= rect.y && y <= rect.y + rect.h;
}

function pointInPolygon(point: { x: number; y: number }, polygon: Point[]): boolean {
  if (polygon.length < 3) return false;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i].x;
    const yi = polygon[i].y;
    const xj = polygon[j].x;
    const yj = polygon[j].y;
    const intersects = yi > point.y !== yj > point.y && point.x < ((xj - xi) * (point.y - yi)) / (yj - yi + 1e-7) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}

export default function NotebookCanvasPage() {
  const [requestedSessionId] = useState(() => new URLSearchParams(window.location.search).get("session_id") || "");
  const [requestedNotebookId] = useState(() => new URLSearchParams(window.location.search).get("notebook_id") || "");
  const queryReady = true;

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasShellRef = useRef<HTMLDivElement | null>(null);
  const currentStrokeRef = useRef<Stroke | null>(null);
  const pointerActiveRef = useRef(false);
  const autosaveTimerRef = useRef<number | null>(null);
  const selectionDraftRef = useRef<SelectionDraft | null>(null);
  const dragStateRef = useRef<DragState | null>(null);
  const overlayDragRef = useRef<OverlayDragState | null>(null);
  const overlayResizeRef = useRef<OverlayResizeState | null>(null);
  const panStateRef = useRef<PanState | null>(null);
  const historyRef = useRef<Record<number, { snapshots: Stroke[][]; index: number }>>({
    0: { snapshots: [[]], index: 0 },
  });

  const [sessionId, setSessionId] = useState("");
  const [title, setTitle] = useState("Advanced Notebook Canvas");
  const [tool, setTool] = useState<ToolType>("pen");
  const [strokeColor, setStrokeColor] = useState("#0F172A");
  const [strokeWidth, setStrokeWidth] = useState(4);
  const [zoom, setZoom] = useState(0.7);
  const [pages, setPages] = useState<CanvasPage[]>([
    { page_index: 0, strokes: [], overlays: [], dirty_regions: [] },
  ]);
  const [currentPageIndex, setCurrentPageIndex] = useState(0);
  const [loadingSession, setLoadingSession] = useState(true);
  const [autosaveEnabled, setAutosaveEnabled] = useState(false);
  const [autosaveState, setAutosaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [processing, setProcessing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [quality, setQuality] = useState<{ ocr_confidence?: number; needs_review?: boolean }>({});
  const [reviewIssues, setReviewIssues] = useState<ReviewIssue[]>([]);
  const [structuredBlocks, setStructuredBlocks] = useState<StructuredBlock[]>([]);
  const [ocrDiagnostics, setOcrDiagnostics] = useState<OcrDiagnostic[]>([]);
  const [reviewEdits, setReviewEdits] = useState<
    Record<string, { text: string; block_type: StructuredBlock["block_type"] }>
  >({});
  const [selectedStrokeIds, setSelectedStrokeIds] = useState<string[]>([]);
  const [selectedOverlayId, setSelectedOverlayId] = useState<string | null>(null);
  const [editingTextId, setEditingTextId] = useState<string | null>(null);
  const [editingEquationId, setEditingEquationId] = useState<string | null>(null);
  const [selectionBox, setSelectionBox] = useState<SelectionRect | null>(null);
  const [eraserCursor, setEraserCursor] = useState<{ x: number; y: number; size: number; visible: boolean }>({
    x: 0,
    y: 0,
    size: strokeWidth,
    visible: false,
  });
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [selectedNotebook, setSelectedNotebook] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [textStyle, setTextStyle] = useState<OverlayTextStyle>(DEFAULT_TEXT_STYLE);

  const currentPage = useMemo(() => {
    return pages.find((page) => page.page_index === currentPageIndex) || pages[0];
  }, [pages, currentPageIndex]);

  const renderEquationPreview = useCallback((latex: string) => {
    const content = String(latex || "").trim();
    if (!content) {
      return { html: "", error: "" };
    }
    try {
      return {
        html: katex.renderToString(content, {
          throwOnError: true,
          displayMode: true,
          strict: "ignore",
        }),
        error: "",
      };
    } catch (err) {
      return {
        html: "",
        error: err instanceof Error ? err.message : "Invalid LaTeX",
      };
    }
  }, []);

  const ensureHistoryPage = useCallback((pageIndex: number, initialStrokes: Stroke[]) => {
    if (!historyRef.current[pageIndex]) {
      historyRef.current[pageIndex] = {
        snapshots: [cloneStrokes(initialStrokes)],
        index: 0,
      };
    }
  }, []);

  const pushHistorySnapshot = useCallback((pageIndex: number, strokes: Stroke[]) => {
    ensureHistoryPage(pageIndex, strokes);
    const history = historyRef.current[pageIndex];
    const nextSnapshots = history.snapshots.slice(0, history.index + 1);
    nextSnapshots.push(cloneStrokes(strokes));
    historyRef.current[pageIndex] = {
      snapshots: nextSnapshots.slice(-120),
      index: Math.min(nextSnapshots.length - 1, 119),
    };
  }, [ensureHistoryPage]);

  const updatePage = useCallback((nextPage: CanvasPage, recordHistory = false) => {
    setPages((prev) => {
      const existing = prev.find((page) => page.page_index === nextPage.page_index);
      if (!existing) {
        return [...prev, nextPage].sort((a, b) => a.page_index - b.page_index);
      }
      return prev.map((page) => (page.page_index === nextPage.page_index ? nextPage : page));
    });
    if (recordHistory) {
      pushHistorySnapshot(nextPage.page_index, nextPage.strokes);
    }
  }, [pushHistorySnapshot]);

  const selectedOverlay = useMemo(() => {
    if (!selectedOverlayId || !currentPage) return null;
    return currentPage.overlays.find((overlay) => overlay.id === selectedOverlayId) || null;
  }, [currentPage, selectedOverlayId]);

  const hasStyleTarget = useMemo(
    () => !!selectedOverlay && (selectedOverlay.type === "text" || selectedOverlay.type === "equation"),
    [selectedOverlay],
  );

  const canvasCursor = useMemo(() => {
    if (tool === "hand") return "grab";
    if (tool === "eraser") return "none";
    return "crosshair";
  }, [tool]);

  const updateOverlay = useCallback(
    (overlayId: string, updater: (overlay: CanvasOverlay) => CanvasOverlay) => {
      if (!currentPage) return null;
      const nextOverlays = currentPage.overlays.map((overlay) =>
        overlay.id === overlayId ? updater(overlay) : overlay,
      );
      const nextPage: CanvasPage = { ...currentPage, overlays: nextOverlays };
      updatePage(nextPage, false);
      return nextPage;
    },
    [currentPage, updatePage],
  );

  const drawStroke = useCallback((ctx: CanvasRenderingContext2D, stroke: Stroke) => {
    if (stroke.points.length === 0) return;
    const isEraser = stroke.tool === "eraser";
    const isHighlighter = stroke.tool === "highlighter";

    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.lineWidth = stroke.width;
    ctx.strokeStyle = stroke.color;
    ctx.fillStyle = stroke.color;
    ctx.globalAlpha = isHighlighter ? 0.28 : 1;
    ctx.globalCompositeOperation = isEraser ? "destination-out" : "source-over";

    if (stroke.tool === "text") {
      const anchor = stroke.points[0];
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
      ctx.fillStyle = stroke.color;
      ctx.font = `${Math.max(16, stroke.width * 1.3)}px ui-sans-serif, system-ui, -apple-system`;
      ctx.textBaseline = "alphabetic";
      ctx.fillText(stroke.text || "", anchor.x, anchor.y);
      ctx.restore();
      return;
    }

    if (stroke.tool === "rect" && stroke.points.length >= 2) {
      const start = stroke.points[0];
      const end = stroke.points[stroke.points.length - 1];
      const x = Math.min(start.x, end.x);
      const y = Math.min(start.y, end.y);
      const w = Math.abs(end.x - start.x);
      const h = Math.abs(end.y - start.y);
      ctx.strokeRect(x, y, w, h);
      ctx.restore();
      return;
    }

    if (stroke.points.length === 1) {
      const dot = stroke.points[0];
      ctx.beginPath();
      ctx.arc(dot.x, dot.y, Math.max(1.5, stroke.width / 2), 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
      return;
    }

    ctx.beginPath();
    ctx.moveTo(stroke.points[0].x, stroke.points[0].y);
    for (const point of stroke.points.slice(1)) {
      ctx.lineTo(point.x, point.y);
    }
    ctx.stroke();
    ctx.restore();
  }, []);

  const buildSnapshotForPage = useCallback(
    (page: CanvasPage): string => {
      if (page.page_index === currentPageIndex && canvasRef.current) {
        return canvasRef.current.toDataURL("image/png", 0.95);
      }
      const offscreen = document.createElement("canvas");
      offscreen.width = CANVAS_WIDTH;
      offscreen.height = CANVAS_HEIGHT;
      const ctx = offscreen.getContext("2d");
      if (!ctx) return "";
      ctx.clearRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
      ctx.fillStyle = "#FFFFFF";
      ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
      for (const stroke of page.strokes) {
        drawStroke(ctx, stroke);
      }
      return offscreen.toDataURL("image/png", 0.95);
    },
    [currentPageIndex, drawStroke],
  );

  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.clearRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);
    ctx.fillStyle = "#FFFFFF";
    ctx.fillRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT);

    for (const stroke of currentPage.strokes) {
      drawStroke(ctx, stroke);
    }
    if (currentStrokeRef.current) {
      drawStroke(ctx, currentStrokeRef.current);
    }

    for (const strokeId of selectedStrokeIds) {
      const selected = currentPage.strokes.find((stroke) => stroke.id === strokeId);
      if (!selected) continue;
      const bounds = strokeBounds(selected);
      if (!bounds) continue;
      ctx.save();
      ctx.strokeStyle = "#4F46E5";
      ctx.lineWidth = 2;
      ctx.setLineDash([6, 4]);
      ctx.strokeRect(bounds.x, bounds.y, bounds.w, bounds.h);
      ctx.restore();
    }

    if (selectionBox) {
      ctx.save();
      ctx.strokeStyle = "#6366F1";
      ctx.lineWidth = 2;
      ctx.setLineDash([8, 4]);
      ctx.strokeRect(selectionBox.x, selectionBox.y, selectionBox.w, selectionBox.h);
      ctx.restore();
    }

    const selectionDraft = selectionDraftRef.current;
    if (selectionDraft && selectionDraft.points.length >= 2) {
      ctx.save();
      ctx.strokeStyle = "#2563EB";
      ctx.lineWidth = 2;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(selectionDraft.points[0].x, selectionDraft.points[0].y);
      for (const point of selectionDraft.points.slice(1)) {
        ctx.lineTo(point.x, point.y);
      }
      if (selectionDraft.kind === "lasso" && selectionDraft.points.length > 2) {
        ctx.closePath();
      }
      ctx.stroke();
      ctx.restore();
    }
  }, [currentPage.strokes, drawStroke, selectedStrokeIds, selectionBox]);

  const pointerToCanvas = useCallback((event: PointerEvent | React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * CANVAS_WIDTH;
    const y = ((event.clientY - rect.top) / rect.height) * CANVAS_HEIGHT;
    return { x, y };
  }, []);

  const handleOverlayPointerDown = useCallback(
    (overlay: CanvasOverlay, event: React.PointerEvent<HTMLButtonElement>) => {
      event.preventDefault();
      event.stopPropagation();
      setSelectedOverlayId(overlay.id);
      if (overlay.type === "text") {
        setEditingTextId(null);
      }
      if (overlay.type === "equation") {
        setEditingEquationId(null);
      }
      setSelectedStrokeIds([]);
      setSelectionBox(null);
      overlayDragRef.current = {
        overlayId: overlay.id,
        startClientX: event.clientX,
        startClientY: event.clientY,
        originX: overlay.x,
        originY: overlay.y,
      };
    },
    [],
  );

  const handleOverlayResizePointerDown = useCallback(
    (overlay: CanvasOverlay, event: React.PointerEvent<HTMLButtonElement>) => {
      event.preventDefault();
      event.stopPropagation();
      setSelectedOverlayId(overlay.id);
      overlayResizeRef.current = {
        overlayId: overlay.id,
        startClientX: event.clientX,
        startClientY: event.clientY,
        originX: overlay.x,
        originY: overlay.y,
        originW: overlay.w,
        originH: overlay.h,
      };
    },
    [],
  );

  const handleOverlayDelete = useCallback(
    (overlayId: string) => {
      if (!currentPage) return;
      const nextPage: CanvasPage = {
        ...currentPage,
        overlays: currentPage.overlays.filter((overlay) => overlay.id !== overlayId),
      };
      updatePage(nextPage, false);
      setSelectedOverlayId((prev) => (prev === overlayId ? null : prev));
      setEditingTextId((prev) => (prev === overlayId ? null : prev));
      setEditingEquationId((prev) => (prev === overlayId ? null : prev));
    },
    [currentPage, updatePage],
  );

  const selectionBoundsFromIds = useCallback((strokes: Stroke[], ids: string[]): SelectionRect | null => {
    const bounds = strokes
      .filter((stroke) => ids.includes(stroke.id))
      .map((stroke) => strokeBounds(stroke))
      .filter(Boolean) as SelectionRect[];
    if (!bounds.length) return null;
    const minX = Math.min(...bounds.map((item) => item.x));
    const minY = Math.min(...bounds.map((item) => item.y));
    const maxX = Math.max(...bounds.map((item) => item.x + item.w));
    const maxY = Math.max(...bounds.map((item) => item.y + item.h));
    return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
  }, []);

  const applySelectionDraft = useCallback((draft: SelectionDraft | null, strokes: Stroke[]) => {
    if (!draft || draft.points.length < 2) {
      setSelectedStrokeIds([]);
      setSelectionBox(null);
      return;
    }

    if (draft.kind === "rect") {
      const start = draft.points[0];
      const end = draft.points[draft.points.length - 1];
      const rect = {
        x: Math.min(start.x, end.x),
        y: Math.min(start.y, end.y),
        w: Math.abs(end.x - start.x),
        h: Math.abs(end.y - start.y),
      };
      const selected = strokes
        .map((stroke) => ({ stroke, bounds: strokeBounds(stroke) }))
        .filter(({ bounds }) => Boolean(bounds))
        .filter(({ bounds }) => {
          if (!bounds) return false;
          return !(
            bounds.x + bounds.w < rect.x ||
            rect.x + rect.w < bounds.x ||
            bounds.y + bounds.h < rect.y ||
            rect.y + rect.h < bounds.y
          );
        })
        .map(({ stroke }) => stroke.id);
      setSelectedStrokeIds(selected);
      setSelectionBox(selectionBoundsFromIds(strokes, selected));
      return;
    }

    const selected = strokes.filter((stroke) => {
      const bounds = strokeBounds(stroke);
      if (!bounds) return false;
      const center = { x: bounds.x + bounds.w / 2, y: bounds.y + bounds.h / 2 };
      return pointInPolygon(center, draft.points);
    });
    const ids = selected.map((stroke) => stroke.id);
    setSelectedStrokeIds(ids);
    setSelectionBox(selectionBoundsFromIds(strokes, ids));
  }, [selectionBoundsFromIds]);

  const persistCurrentPage = useCallback(
    async (page: CanvasPage) => {
      if (!sessionId) return;
      setAutosaveState("saving");
      try {
        const snapshotDataUrl = buildSnapshotForPage(page);
        const response = await apiFetch(apiUrl(`/api/v1/notebook/canvas/sessions/${sessionId}/strokes:batch`), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            page_index: page.page_index,
            strokes: page.strokes,
            overlays: page.overlays || [],
            dirty_regions: page.dirty_regions,
            snapshot_data_url: snapshotDataUrl || undefined,
            replace_page: true,
          }),
        });
        if (!response.ok) {
          throw new Error("Autosave failed.");
        }
        setAutosaveState("saved");
        window.setTimeout(() => setAutosaveState("idle"), 1200);
      } catch (saveError) {
        console.error(saveError);
        setAutosaveState("error");
      }
    },
    [buildSnapshotForPage, sessionId],
  );

  const queueAutosave = useCallback((pageOverride?: CanvasPage) => {
    if (!sessionId || !autosaveEnabled) return;
    const pageToSave = pageOverride || currentPage;
    if (!pageToSave) return;
    if (autosaveTimerRef.current) {
      window.clearTimeout(autosaveTimerRef.current);
    }
    autosaveTimerRef.current = window.setTimeout(() => {
      void persistCurrentPage(pageToSave);
    }, 600);
  }, [autosaveEnabled, sessionId, currentPage, persistCurrentPage]);

  const flushAutosave = useCallback(async () => {
    if (!currentPage) return;
    if (autosaveTimerRef.current) {
      window.clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
    }
    await persistCurrentPage(currentPage);
  }, [currentPage, persistCurrentPage]);

  const persistAllPages = useCallback(async () => {
    if (!sessionId) return;
    for (const page of pages) {
      await persistCurrentPage(page);
    }
  }, [pages, persistCurrentPage, sessionId]);

  const applySelectedTextStyle = useCallback(
    (updater: OverlayTextStyle | ((prev: OverlayTextStyle) => OverlayTextStyle)) => {
      if (
        !selectedOverlayId ||
        !selectedOverlay ||
        (selectedOverlay.type !== "text" && selectedOverlay.type !== "equation")
      ) {
        return;
      }

      const baseStyle = {
        ...DEFAULT_TEXT_STYLE,
        ...(selectedOverlay.style || {}),
      };

      const nextStyle =
        typeof updater === "function"
          ? (updater as (prev: OverlayTextStyle) => OverlayTextStyle)(baseStyle)
          : updater;

      setTextStyle(nextStyle);

      const nextPage = updateOverlay(selectedOverlayId, (overlay) => ({
        ...overlay,
        style: {
          ...DEFAULT_TEXT_STYLE,
          ...(overlay.style || {}),
          ...nextStyle,
        },
      }));

      if (autosaveEnabled && nextPage) {
        queueAutosave(nextPage);
      } else {
        setAutosaveState("idle");
      }
    },
    [
      autosaveEnabled,
      queueAutosave,
      selectedOverlay,
      selectedOverlayId,
      textStyle,
      updateOverlay,
    ],
  );

  const computeDirtyRect = useCallback((strokes: Stroke[]): SelectionRect | null => {
    const bounds = strokes.map((stroke) => strokeBounds(stroke)).filter(Boolean) as SelectionRect[];
    if (!bounds.length) return null;
    const minX = Math.max(0, Math.min(...bounds.map((item) => item.x)));
    const minY = Math.max(0, Math.min(...bounds.map((item) => item.y)));
    const maxX = Math.min(CANVAS_WIDTH, Math.max(...bounds.map((item) => item.x + item.w)));
    const maxY = Math.min(CANVAS_HEIGHT, Math.max(...bounds.map((item) => item.y + item.h)));
    return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
  }, []);

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLCanvasElement>) => {
      event.preventDefault();
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch {
        // no-op on unsupported pointer capture environments
      }
      const point = pointerToCanvas(event);
      if (!point) return;
      setError("");
      setNotice("");

      if (tool === "hand") {
        pointerActiveRef.current = true;
        currentStrokeRef.current = null;
        selectionDraftRef.current = null;
        dragStateRef.current = null;
        if (containerRef.current) {
          panStateRef.current = {
            startClientX: event.clientX,
            startClientY: event.clientY,
            scrollLeft: containerRef.current.scrollLeft,
            scrollTop: containerRef.current.scrollTop,
          };
        }
        return;
      }

      if ((tool === "text_box" || tool === "equation") && currentPage) {
        const nextOverlay: CanvasOverlay = {
          id: uid(tool === "equation" ? "eq" : "txt"),
          type: tool === "equation" ? "equation" : "text",
          x: Math.max(0, Math.min(CANVAS_WIDTH - 360, point.x)),
          y: Math.max(0, Math.min(CANVAS_HEIGHT - 140, point.y)),
          w: tool === "equation" ? 420 : 360,
          h: tool === "equation" ? 180 : 120,
          text: tool === "equation" ? "\\frac{a}{b}" : "",
          style: {
            ...DEFAULT_TEXT_STYLE,
          },
        };
        const nextPage: CanvasPage = {
          ...currentPage,
          overlays: [...currentPage.overlays, nextOverlay],
        };
        updatePage(nextPage, false);
        if (autosaveEnabled) {
          queueAutosave(nextPage);
        } else {
          setAutosaveState("idle");
        }
        setSelectedOverlayId(nextOverlay.id);
        setEditingTextId(tool === "text_box" ? nextOverlay.id : null);
        setEditingEquationId(tool === "equation" ? nextOverlay.id : null);
        setSelectedStrokeIds([]);
        setSelectionBox(null);
        pointerActiveRef.current = false;
        currentStrokeRef.current = null;
        selectionDraftRef.current = null;
        redraw();
        return;
      }

      if (tool === "text" && currentPage) {
        const text = window.prompt("Enter text for canvas");
        if (text && text.trim()) {
          const nextStroke: Stroke = {
            id: uid("text"),
            tool: "text",
            color: strokeColor,
            width: Math.max(14, strokeWidth * 4),
            points: [{ x: point.x, y: point.y, t: Date.now() }],
            layer_id: "layer_main",
            text: text.trim(),
          };
          const dirty = computeDirtyRect([nextStroke]);
          const nextPage: CanvasPage = {
            ...currentPage,
            strokes: [...currentPage.strokes, nextStroke],
            dirty_regions: dirty ? [...currentPage.dirty_regions.slice(-40), dirty] : currentPage.dirty_regions,
          };
          updatePage(nextPage, true);
          if (autosaveEnabled) {
            queueAutosave(nextPage);
          }
          setSelectedStrokeIds([nextStroke.id]);
          setSelectedOverlayId(null);
          setSelectionBox(selectionBoundsFromIds(nextPage.strokes, [nextStroke.id]));
        }
        pointerActiveRef.current = false;
        currentStrokeRef.current = null;
        selectionDraftRef.current = null;
        redraw();
        return;
      }

      if ((tool === "select_rect" || tool === "select_lasso") && currentPage) {
        pointerActiveRef.current = true;
        setSelectedOverlayId(null);
        if (selectionBox && selectedStrokeIds.length > 0 && rectContainsPoint(selectionBox, point.x, point.y)) {
          dragStateRef.current = {
            active: true,
            startX: point.x,
            startY: point.y,
            baseStrokes: cloneStrokes(currentPage.strokes),
          };
          selectionDraftRef.current = null;
          return;
        }
        dragStateRef.current = null;
        selectionDraftRef.current = {
          kind: tool === "select_lasso" ? "lasso" : "rect",
          points: [{ x: point.x, y: point.y, t: Date.now() }],
        };
        setSelectedStrokeIds([]);
        setSelectionBox(null);
        redraw();
        return;
      }

      pointerActiveRef.current = true;
      setSelectedStrokeIds([]);
      setSelectedOverlayId(null);
      setEditingTextId(null);
      setEditingEquationId(null);
      setSelectionBox(null);
      const width = tool === "highlighter" ? Math.max(strokeWidth + 6, 10) : strokeWidth;
      currentStrokeRef.current = {
        id: uid("stroke"),
        tool,
        color: tool === "eraser" ? "#FFFFFF" : strokeColor,
        width,
        points: [{ x: point.x, y: point.y, t: Date.now() }],
        layer_id: "layer_main",
      };
      redraw();
    },
    [
      pointerToCanvas,
      tool,
      strokeColor,
      strokeWidth,
      redraw,
      currentPage,
      computeDirtyRect,
      updatePage,
      queueAutosave,
      selectionBox,
      selectedStrokeIds,
      selectionBoundsFromIds,
    ],
  );

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLCanvasElement>) => {
      const point = pointerToCanvas(event);
      if (!point) return;

      if (tool === "eraser") {
        setEraserCursor({ x: point.x, y: point.y, size: strokeWidth, visible: true });
      } else if (eraserCursor.visible) {
        setEraserCursor((prev) => ({ ...prev, visible: false }));
      }

      if (!pointerActiveRef.current) return;
      event.preventDefault();
      if (tool === "hand") {
        const pan = panStateRef.current;
        const container = containerRef.current;
        if (pan && container) {
          const dx = event.clientX - pan.startClientX;
          const dy = event.clientY - pan.startClientY;
          container.scrollLeft = pan.scrollLeft - dx;
          container.scrollTop = pan.scrollTop - dy;
        }
        return;
      }

      if ((tool === "select_rect" || tool === "select_lasso") && currentPage) {
        const dragState = dragStateRef.current;
        if (dragState?.active) {
          const dx = point.x - dragState.startX;
          const dy = point.y - dragState.startY;
          const moved = dragState.baseStrokes.map((stroke) => {
            if (!selectedStrokeIds.includes(stroke.id)) return stroke;
            return {
              ...stroke,
              points: stroke.points.map((p) => ({ ...p, x: p.x + dx, y: p.y + dy })),
            };
          });
          const nextPage = { ...currentPage, strokes: moved };
          updatePage(nextPage, false);
          setSelectionBox(selectionBoundsFromIds(moved, selectedStrokeIds));
          return;
        }

        if (selectionDraftRef.current) {
          const nextPoints = [...selectionDraftRef.current.points, { x: point.x, y: point.y, t: Date.now() }];
          if (selectionDraftRef.current.kind === "rect") {
            selectionDraftRef.current = {
              ...selectionDraftRef.current,
              points: [selectionDraftRef.current.points[0], nextPoints[nextPoints.length - 1]],
            };
          } else {
            selectionDraftRef.current = { ...selectionDraftRef.current, points: nextPoints };
          }
          redraw();
          return;
        }
      }

      if (!currentStrokeRef.current) return;
      const points = currentStrokeRef.current.points;
      points.push({ x: point.x, y: point.y, t: Date.now() });
      currentStrokeRef.current = { ...currentStrokeRef.current, points };
      redraw();
    },
    [
      pointerToCanvas,
      redraw,
      tool,
      currentPage,
      selectedStrokeIds,
      selectionBoundsFromIds,
      updatePage,
      strokeWidth,
      eraserCursor.visible,
    ],
  );

  const finishStroke = useCallback(() => {
    if (!pointerActiveRef.current || !currentPage) {
      pointerActiveRef.current = false;
      currentStrokeRef.current = null;
      selectionDraftRef.current = null;
      dragStateRef.current = null;
      panStateRef.current = null;
      return;
    }

    if (tool === "hand") {
      pointerActiveRef.current = false;
      panStateRef.current = null;
      return;
    }

    if (tool === "select_rect" || tool === "select_lasso") {
      const dragState = dragStateRef.current;
      if (dragState?.active) {
        const dirty = computeDirtyRect(
          currentPage.strokes.filter((stroke) => selectedStrokeIds.includes(stroke.id)),
        );
        if (dirty) {
          const nextPage: CanvasPage = {
            ...currentPage,
            dirty_regions: [...currentPage.dirty_regions.slice(-40), dirty],
          };
          updatePage(nextPage, true);
          queueAutosave(nextPage);
        } else {
          pushHistorySnapshot(currentPage.page_index, currentPage.strokes);
        }
        dragStateRef.current = null;
        pointerActiveRef.current = false;
        redraw();
        return;
      }

      applySelectionDraft(selectionDraftRef.current, currentPage.strokes);
      selectionDraftRef.current = null;
      pointerActiveRef.current = false;
      redraw();
      return;
    }

    if (!currentStrokeRef.current) {
      pointerActiveRef.current = false;
      return;
    }

    pointerActiveRef.current = false;
    const stroke = currentStrokeRef.current;
    currentStrokeRef.current = null;
    if (stroke.points.length < 1) return;
    const xs = stroke.points.map((point) => point.x);
    const ys = stroke.points.map((point) => point.y);
    const dirty = {
      x: Math.max(0, Math.min(...xs) - stroke.width - 2),
      y: Math.max(0, Math.min(...ys) - stroke.width - 2),
      w: Math.min(CANVAS_WIDTH, Math.max(...xs) - Math.min(...xs) + stroke.width * 2 + 4),
      h: Math.min(CANVAS_HEIGHT, Math.max(...ys) - Math.min(...ys) + stroke.width * 2 + 4),
    };
    const nextPage: CanvasPage = {
      ...currentPage,
      strokes: [...currentPage.strokes, stroke],
      dirty_regions: [...currentPage.dirty_regions.slice(-40), dirty],
    };
    updatePage(nextPage, true);
    queueAutosave(nextPage);
    redraw();
  }, [
    currentPage,
    queueAutosave,
    tool,
    applySelectionDraft,
    computeDirtyRect,
    selectedStrokeIds,
    redraw,
    updatePage,
    pushHistorySnapshot,
  ]);

  const handlePointerLeave = useCallback(() => {
    setEraserCursor((prev) => ({ ...prev, visible: false }));
    finishStroke();
  }, [finishStroke]);

  const createSession = useCallback(() => apiFetch(apiUrl("/api/v1/notebook/canvas/sessions"), {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: "Advanced Notebook Canvas" }),
  }).then(response => { if (!response.ok) throw new Error(`Canvas HTTP ${response.status}`); return response.json(); })
    .then(data => {
      if (!data.success) {
        throw new Error(data.detail || "Failed to create canvas session.");
      }
      setSessionId(data.session.session_id);
      setTitle(data.session.title || "Advanced Notebook Canvas");
      setPages([{ page_index: 0, strokes: [], overlays: [], dirty_regions: [] }]);
      setCurrentPageIndex(0);
      setSelectedOverlayId(null);
      setSelectedStrokeIds([]);
      setSelectionBox(null);
      setAutosaveEnabled(false);
      setNotice(`Session ready: ${data.session.session_id}`);
    }).catch(error => setError(error instanceof Error ? error.message : "Unable to initialize canvas session"))
    .finally(() => setLoadingSession(false)), []);

  const loadExistingSession = useCallback((targetSessionId: string) => apiFetch(apiUrl(`/api/v1/notebook/canvas/sessions/${targetSessionId}`))
    .then(response => { if (!response.ok) throw new Error(`Canvas HTTP ${response.status}`); return response.json(); })
    .then(data => {
      if (!data.success || !data.session) {
        throw new Error(data.detail || "Failed to load existing canvas session.");
      }
      const session = data.session as {
        session_id: string;
        title?: string;
        notebook_id?: string;
        pages?: Array<{
          page_index: number;
          strokes?: Stroke[];
          overlays?: CanvasOverlay[];
          dirty_regions?: Array<{ x: number; y: number; w: number; h: number }>;
        }>;
        quality?: { ocr_confidence?: number; needs_review?: boolean };
        review_issues?: ReviewIssue[];
        structured?: { blocks?: StructuredBlock[] };
      };
      const sessionPages: CanvasPage[] = (session.pages || []).map((page) => ({
        page_index: page.page_index,
        strokes: page.strokes || [],
        overlays: page.overlays || [],
        dirty_regions: page.dirty_regions || [],
      }));
      const nextPages =
        sessionPages.length > 0
          ? sessionPages.sort((a, b) => a.page_index - b.page_index)
          : [{ page_index: 0, strokes: [], overlays: [], dirty_regions: [] }];
      setSessionId(session.session_id);
      setTitle(session.title || "Advanced Notebook Canvas");
      setPages(nextPages);
      setCurrentPageIndex(nextPages[0].page_index || 0);
      setSelectedOverlayId(null);
      setSelectedStrokeIds([]);
      setSelectionBox(null);
      setQuality(session.quality || {});
      setReviewIssues(session.review_issues || []);
      setStructuredBlocks(session.structured?.blocks || []);
      setAutosaveEnabled(true);
      if (session.notebook_id) {
        setSelectedNotebook(session.notebook_id);
      }
      for (const page of nextPages) {
        ensureHistoryPage(page.page_index, page.strokes);
      }
      setNotice(`Loaded existing session: ${session.session_id}`);
    }).catch(error => setError(error instanceof Error ? error.message : "Unable to load canvas session"))
    .finally(() => setLoadingSession(false)), [ensureHistoryPage]);

  const fetchNotebooks = useCallback(() => apiFetch(apiUrl("/api/v1/notebook/list"))
    .then(response => { if (!response.ok) throw new Error(`Notebooks HTTP ${response.status}`); return response.json(); })
    .then(data => {
      const list = (data.notebooks || []) as NotebookSummary[]; setNotebooks(list);
      setSelectedNotebook(prev => prev || requestedNotebookId || list[0]?.id || "");
    }).catch(error => console.error(error)), [requestedNotebookId]);

  const runProcess = useCallback(async () => {
    if (!sessionId) return;
    setProcessing(true);
    setError("");
    try {
      await persistAllPages();
      const response = await apiFetch(apiUrl(`/api/v1/notebook/canvas/sessions/${sessionId}/process`), {
        method: "POST",
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.detail || "Process failed.");
      }
      const session = data.session;
      setQuality(session.quality || {});
      setReviewIssues((session.review_issues || []) as ReviewIssue[]);
      setOcrDiagnostics((session.ocr_diagnostics || []) as OcrDiagnostic[]);
      const blocks = (session.structured?.blocks || []) as StructuredBlock[];
      setStructuredBlocks(blocks);
      const edits: Record<string, { text: string; block_type: StructuredBlock["block_type"] }> = {};
      for (const block of blocks) {
        edits[block.id] = {
          text: block.normalized_text,
          block_type: block.block_type,
        };
      }
      setReviewEdits(edits);
      const fallbackDiag = ((session.ocr_diagnostics || []) as OcrDiagnostic[]).find((diag) => diag.used_fallback);
      if (fallbackDiag?.message) {
        setNotice(`OCR completed with fallback: ${fallbackDiag.message}`);
      } else {
        setNotice("OCR + structure completed.");
      }
    } catch (processError: unknown) {
      const message = processError instanceof Error ? processError.message : "Failed to process OCR.";
      setError(message);
    } finally {
      setProcessing(false);
    }
  }, [sessionId, persistAllPages]);

  const submitConfirm = useCallback(async () => {
    if (!sessionId) return;
    setConfirming(true);
    setError("");
    try {
      const updates = Object.entries(reviewEdits).map(([id, payload]) => ({
        id,
        text: payload.text,
        block_type: payload.block_type,
      }));
      const response = await apiFetch(apiUrl(`/api/v1/notebook/canvas/sessions/${sessionId}/confirm`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ block_updates: updates }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.detail || "Confirm failed.");
      }
      setReviewIssues((data.review_issues || []) as ReviewIssue[]);
      setQuality(data.session?.quality || {});
      setNotice("Review confirmation saved.");
    } catch (confirmError: unknown) {
      const message = confirmError instanceof Error ? confirmError.message : "Confirm failed.";
      setError(message);
    } finally {
      setConfirming(false);
    }
  }, [sessionId, reviewEdits]);

  const commitToNotebook = useCallback(async () => {
    if (!sessionId || !selectedNotebook) {
      setError("Please select a notebook before commit.");
      return;
    }
    setCommitting(true);
    setError("");
    try {
      await persistAllPages();
      const response = await apiFetch(apiUrl(`/api/v1/notebook/canvas/sessions/${sessionId}/commit`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          notebook_id: selectedNotebook,
          title,
          user_query: `Canvas session ${sessionId}`,
        }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        throw new Error(data.detail || "Commit failed.");
      }
      setNotice(`Saved to notebook. Record: ${data.record?.id || "created"}`);
    } catch (commitError: unknown) {
      const message = commitError instanceof Error ? commitError.message : "Commit failed.";
      setError(message);
    } finally {
      setCommitting(false);
    }
  }, [sessionId, selectedNotebook, title, persistAllPages]);

  const undo = useCallback(() => {
    if (!currentPage) return;
    ensureHistoryPage(currentPageIndex, currentPage.strokes);
    const history = historyRef.current[currentPageIndex];
    if (!history || history.index <= 0) return;
    historyRef.current[currentPageIndex] = { ...history, index: history.index - 1 };
    const strokes = cloneStrokes(history.snapshots[history.index - 1] || []);
    const dirty = computeDirtyRect(strokes);
    const nextPage: CanvasPage = {
      ...currentPage,
      strokes,
      dirty_regions: dirty ? [...currentPage.dirty_regions.slice(-40), dirty] : currentPage.dirty_regions,
    };
    updatePage(nextPage, false);
    setSelectedStrokeIds([]);
    setSelectionBox(null);
    queueAutosave(nextPage);
  }, [currentPage, currentPageIndex, ensureHistoryPage, computeDirtyRect, updatePage, queueAutosave]);

  const redo = useCallback(() => {
    if (!currentPage) return;
    ensureHistoryPage(currentPageIndex, currentPage.strokes);
    const history = historyRef.current[currentPageIndex];
    if (!history || history.index >= history.snapshots.length - 1) return;
    historyRef.current[currentPageIndex] = { ...history, index: history.index + 1 };
    const strokes = cloneStrokes(history.snapshots[history.index + 1] || []);
    const dirty = computeDirtyRect(strokes);
    const nextPage: CanvasPage = {
      ...currentPage,
      strokes,
      dirty_regions: dirty ? [...currentPage.dirty_regions.slice(-40), dirty] : currentPage.dirty_regions,
    };
    updatePage(nextPage, false);
    setSelectedStrokeIds([]);
    setSelectionBox(null);
    queueAutosave(nextPage);
  }, [currentPage, currentPageIndex, ensureHistoryPage, computeDirtyRect, updatePage, queueAutosave]);

  const addNewPage = useCallback(() => {
    const nextIndex = Math.max(...pages.map((page) => page.page_index)) + 1;
    const nextPage: CanvasPage = { page_index: nextIndex, strokes: [], overlays: [], dirty_regions: [] };
    setPages((prev) => [...prev, nextPage]);
    ensureHistoryPage(nextIndex, []);
    setCurrentPageIndex(nextIndex);
    setSelectedOverlayId(null);
  }, [pages, ensureHistoryPage]);

  useEffect(() => {
    if (!queryReady) return;
    void fetchNotebooks();
    if (requestedSessionId) {
      void loadExistingSession(requestedSessionId);
    } else {
      void createSession();
    }
  }, [createSession, fetchNotebooks, loadExistingSession, queryReady, requestedSessionId]);

  useEffect(() => {
    if (!currentPage) return;
    ensureHistoryPage(currentPage.page_index, currentPage.strokes);
  }, [currentPage, ensureHistoryPage]);

  const [previousOverlay, setPreviousOverlay] = useState(selectedOverlay);
  if (previousOverlay !== selectedOverlay) {
    setPreviousOverlay(selectedOverlay);
    setTextStyle(selectedOverlay && (selectedOverlay.type === "text" || selectedOverlay.type === "equation") ? { ...DEFAULT_TEXT_STYLE, ...selectedOverlay.style } : DEFAULT_TEXT_STYLE);
    if (selectedOverlay?.type !== "text") setEditingTextId(null);
    if (selectedOverlay?.type !== "equation") setEditingEquationId(null);
  }

  useEffect(() => {
    if (!autosaveEnabled || !currentPage || loadingSession) return;
    queueAutosave(currentPage);
    // Intentionally debounce via queueAutosave internal timer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autosaveEnabled, currentPage?.overlays, loadingSession]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tag = (target?.tagName || "").toLowerCase();
      const isEditable = target?.isContentEditable || tag === "input" || tag === "textarea" || tag === "select";
      if (isEditable) return;
      const isPrimary = event.ctrlKey || event.metaKey;
      if (!isPrimary) return;

      const key = event.key.toLowerCase();
      if (key === "z") {
        event.preventDefault();
        if (event.shiftKey) {
          redo();
        } else {
          undo();
        }
      } else if (key === "y") {
        event.preventDefault();
        redo();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [undo, redo]);

  useEffect(() => {
    const onPointerMove = (event: PointerEvent) => {
      if (!currentPage) return;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;

      const resize = overlayResizeRef.current;
      if (resize) {
        const dw = ((event.clientX - resize.startClientX) / rect.width) * CANVAS_WIDTH;
        const dh = ((event.clientY - resize.startClientY) / rect.height) * CANVAS_HEIGHT;
        const nextPage: CanvasPage = {
          ...currentPage,
          overlays: currentPage.overlays.map((overlay) => {
            if (overlay.id !== resize.overlayId) return overlay;
            const nextW = Math.max(120, Math.min(CANVAS_WIDTH - resize.originX, resize.originW + dw));
            const nextH = Math.max(56, Math.min(CANVAS_HEIGHT - resize.originY, resize.originH + dh));
            return {
              ...overlay,
              w: nextW,
              h: nextH,
            };
          }),
        };
        updatePage(nextPage, false);
        return;
      }

      const drag = overlayDragRef.current;
      if (!drag) return;
      const dx = ((event.clientX - drag.startClientX) / rect.width) * CANVAS_WIDTH;
      const dy = ((event.clientY - drag.startClientY) / rect.height) * CANVAS_HEIGHT;
      const nextPage: CanvasPage = {
        ...currentPage,
        overlays: currentPage.overlays.map((overlay) => {
          if (overlay.id !== drag.overlayId) return overlay;
          return {
            ...overlay,
            x: Math.max(0, Math.min(CANVAS_WIDTH - overlay.w, drag.originX + dx)),
            y: Math.max(0, Math.min(CANVAS_HEIGHT - overlay.h, drag.originY + dy)),
          };
        }),
      };
      updatePage(nextPage, false);
    };

    const onPointerUp = () => {
      if (!overlayDragRef.current && !overlayResizeRef.current) return;
      overlayDragRef.current = null;
      overlayResizeRef.current = null;
      const latestPage = pages.find((page) => page.page_index === currentPageIndex);
      if (autosaveEnabled && latestPage) {
        queueAutosave(latestPage);
      }
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
    };
  }, [autosaveEnabled, currentPage, currentPageIndex, pages, queueAutosave, updatePage]);

  useEffect(() => {
    return () => {
      if (autosaveTimerRef.current) {
        window.clearTimeout(autosaveTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    redraw();
  }, [redraw, currentPageIndex]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.width = CANVAS_WIDTH;
    canvas.height = CANVAS_HEIGHT;
    redraw();
  }, [redraw]);

  return (
    <div className="h-screen p-4 flex gap-4 overflow-hidden">
      <div className="w-[300px] bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-sm flex flex-col overflow-hidden">
        <div className="p-4 border-b border-slate-100 dark:border-slate-700">
          <Link
            href="/notebook"
            className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700 dark:text-slate-300 dark:hover:text-slate-100"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            Back to Notebook
          </Link>
          <h1 className="text-lg font-bold mt-2 text-slate-900 dark:text-slate-100">
            Advanced Notebook Canvas
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Session: {loadingSession ? "initializing..." : sessionId}
          </p>
        </div>

        <div className="p-4 space-y-4 overflow-y-auto flex-1">
          <div>
            <label className="text-xs uppercase tracking-wider font-semibold text-slate-500 dark:text-slate-400">
              Canvas Title
            </label>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm"
            />
          </div>

          <div>
            <label className="text-xs uppercase tracking-wider font-semibold text-slate-500 dark:text-slate-400">
              Tool
            </label>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {[
                { id: "hand", icon: Move, label: "Hand" },
                { id: "pen", icon: PenLine, label: "Pen" },
                { id: "highlighter", icon: Palette, label: "Highlighter" },
                { id: "eraser", icon: Eraser, label: "Eraser" },
                { id: "rect", icon: Square, label: "Rect" },
                { id: "text_box", icon: Type, label: "Typing (T)" },
                { id: "equation", icon: Sigma, label: "Equation" },
                { id: "select_rect", icon: SquareDashedMousePointer, label: "Select Rect" },
                { id: "select_lasso", icon: LassoSelect, label: "Lasso Select" },
              ].map((item) => (
                <button
                  key={item.id}
                  onClick={() => setTool(item.id as ToolType)}
                  className={`rounded-lg border px-2 py-2 text-xs font-medium inline-flex items-center justify-center gap-1 ${
                    tool === item.id
                      ? "border-indigo-500 bg-indigo-50 text-indigo-700"
                      : "border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300"
                  }`}
                >
                  <item.icon className="w-3.5 h-3.5" />
                  {item.label}
                </button>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">
              `Hand`: pan canvas. `Typing` / `Equation`: click canvas to add editable box. `Select`: draw region/lasso, then drag strokes to move.
            </p>
          </div>

          <div>
            <label className="text-xs uppercase tracking-wider font-semibold text-slate-500 dark:text-slate-400">
              Color
            </label>
            <div className="mt-2 flex flex-wrap gap-2">
              {COLORS.map((color) => (
                <button
                  key={color}
                  onClick={() => setStrokeColor(color)}
                  className={`w-7 h-7 rounded-full border-2 ${
                    strokeColor === color ? "border-slate-900 dark:border-slate-100" : "border-transparent"
                  }`}
                  style={{ backgroundColor: color }}
                />
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs uppercase tracking-wider font-semibold text-slate-500 dark:text-slate-400">
              Brush Size
            </label>
            <input
              type="range"
              min={2}
              max={24}
              value={strokeWidth}
              onChange={(event) => setStrokeWidth(Number(event.target.value))}
              className="w-full mt-2"
            />
          </div>

          <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3 space-y-3">
            <label className="text-xs uppercase tracking-wider font-semibold text-slate-500 dark:text-slate-400">
              Typing / Equation Style
            </label>
            <div className="grid grid-cols-2 gap-2">
              <select
                value={textStyle.fontFamily}
                disabled={!hasStyleTarget}
                onChange={(event) =>
                  applySelectedTextStyle((prev) => ({
                    ...prev,
                    fontFamily: event.target.value,
                  }))
                }
                className="rounded border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-2 py-1 text-xs"
              >
                {TEXT_FONTS.map((font) => (
                  <option key={font} value={font}>
                    {font}
                  </option>
                ))}
              </select>
              <input
                type="number"
                min={12}
                max={72}
                value={textStyle.fontSize}
                disabled={!hasStyleTarget}
                onChange={(event) =>
                  applySelectedTextStyle((prev) => ({
                    ...prev,
                    fontSize: Math.max(12, Math.min(72, Number(event.target.value) || 12)),
                  }))
                }
                className="rounded border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-2 py-1 text-xs"
              />
            </div>
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={textStyle.color}
                disabled={!hasStyleTarget}
                onChange={(event) =>
                  applySelectedTextStyle((prev) => ({ ...prev, color: event.target.value }))
                }
                className="h-8 w-10 rounded border border-slate-200 dark:border-slate-600 bg-white"
              />
              {[
                { id: "bold", label: "B" },
                { id: "italic", label: "I" },
                { id: "underline", label: "U" },
                { id: "strike", label: "S" },
                { id: "highlight", label: "H" },
              ].map((item) => (
                <button
                  key={item.id}
                  disabled={!hasStyleTarget}
                  onClick={() =>
                    applySelectedTextStyle((prev) => ({
                      ...prev,
                      [item.id]: !prev[item.id as TextBooleanKey],
                    }))
                  }
                  className={`h-8 w-8 rounded border text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50 ${
                    textStyle[item.id as TextBooleanKey]
                      ? "border-indigo-400 bg-indigo-50 text-indigo-700"
                      : "border-slate-200 dark:border-slate-600 text-slate-600 dark:text-slate-300"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              Select a typing or equation box to edit that box only. New boxes start with the default style.
            </p>
          </div>

          <div>
            <label className="text-xs uppercase tracking-wider font-semibold text-slate-500 dark:text-slate-400">
              Target Notebook
            </label>
            <select
              value={selectedNotebook}
              onChange={(event) => setSelectedNotebook(event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm"
            >
              {notebooks.map((notebook) => (
                <option key={notebook.id} value={notebook.id}>
                  {notebook.name} ({notebook.record_count})
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="p-4 border-t border-slate-100 dark:border-slate-700 space-y-2">
          <button
            onClick={() => void persistAllPages()}
            disabled={!sessionId}
            className="w-full rounded-lg border border-slate-200 dark:border-slate-600 text-sm font-semibold py-2.5 inline-flex items-center justify-center gap-2 disabled:opacity-50"
          >
            <Save className="w-4 h-4" />
            Save Draft
          </button>
          <button
            onClick={runProcess}
            disabled={processing || !sessionId}
            className="w-full rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold py-2.5 inline-flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {processing ? <Loader2 className="w-4 h-4 animate-spin" /> : <ScanLine className="w-4 h-4" />}
            Recognize & Structure
          </button>
          <button
            onClick={submitConfirm}
            disabled={confirming || Object.keys(reviewEdits).length === 0}
            className="w-full rounded-lg border border-slate-200 dark:border-slate-600 text-sm font-semibold py-2.5 inline-flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {confirming ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
            Confirm OCR
          </button>
          <button
            onClick={commitToNotebook}
            disabled={committing || !selectedNotebook}
            className="w-full rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-700 text-sm font-semibold py-2.5 inline-flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {committing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            Save to Notebook
          </button>
          <div className="text-[11px] text-slate-500 dark:text-slate-400">
            Autosave:{" "}
            {!autosaveEnabled
              ? "Off (new canvas)"
              : autosaveState === "saving"
                ? "Saving..."
                : autosaveState === "saved"
                  ? "Saved"
                  : autosaveState === "error"
                    ? "Error"
                    : "Idle"}
          </div>
        </div>
      </div>

      <div className="flex-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-sm flex flex-col overflow-hidden">
        <div className="p-3 border-b border-slate-100 dark:border-slate-700 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MousePointer2 className="w-4 h-4 text-indigo-600" />
            <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              Page {currentPageIndex + 1}
            </span>
            {selectedStrokeIds.length > 0 && (
              <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-indigo-200 bg-indigo-50 text-indigo-700">
                <Move className="w-3 h-3" />
                {selectedStrokeIds.length} selected
              </span>
            )}
            <button
              onClick={addNewPage}
              className="inline-flex items-center gap-1 text-xs px-2 py-1 border rounded-md"
            >
              <Plus className="w-3 h-3" />
              Add Page
            </button>
            <button
              onClick={undo}
              className="inline-flex items-center gap-1 text-xs px-2 py-1 border rounded-md"
              title="Undo (Ctrl/Cmd+Z)"
            >
              <Undo2 className="w-3 h-3" />
              Undo
            </button>
            <button
              onClick={redo}
              className="inline-flex items-center gap-1 text-xs px-2 py-1 border rounded-md"
              title="Redo (Ctrl/Cmd+Shift+Z or Ctrl/Cmd+Y)"
            >
              <Redo2 className="w-3 h-3" />
              Redo
            </button>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">Zoom</span>
            <input
              type="range"
              min={0.35}
              max={1}
              step={0.05}
              value={zoom}
              onChange={(event) => setZoom(Number(event.target.value))}
            />
          </div>
        </div>

        <div className="flex-1 overflow-auto bg-slate-100 dark:bg-slate-900 p-5" ref={containerRef}>
          <div
            ref={canvasShellRef}
            className="mx-auto shadow-xl border border-slate-300 bg-white touch-none"
            style={{
              width: `${CANVAS_WIDTH * zoom}px`,
              height: `${CANVAS_HEIGHT * zoom}px`,
              position: "relative",
            }}
          >
            <canvas
              ref={canvasRef}
              className="h-full w-full"
              style={{ cursor: canvasCursor }}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={finishStroke}
              onPointerCancel={handlePointerLeave}
              onPointerLeave={handlePointerLeave}
            />
            {(currentPage?.overlays || []).map((overlay) => {
              const selected = selectedOverlayId === overlay.id;
              const isTextEditing = overlay.type === "text" && editingTextId === overlay.id;
              const isEquationEditing = overlay.type === "equation" && editingEquationId === overlay.id;
              const preview = overlay.type === "equation" ? renderEquationPreview(overlay.text) : null;
              const isEditing = isTextEditing || isEquationEditing;
              const textDecoration = [
                overlay.style.underline ? "underline" : "",
                overlay.style.strike ? "line-through" : "",
              ]
                .filter(Boolean)
                .join(" ");
              const baseBackground =
                overlay.style.highlight && isEditing
                  ? "rgba(254, 240, 138, 0.3)"
                  : isEditing
                    ? "rgba(255,255,255,0.08)"
                    : "transparent";

              return (
                <div
                  key={overlay.id}
                  className={`group absolute ${selected ? "z-20" : "z-10"}`}
                  style={{
                    left: `${overlay.x * zoom}px`,
                    top: `${overlay.y * zoom}px`,
                    width: `${overlay.w * zoom}px`,
                    height: `${overlay.h * zoom}px`,
                  }}
                  onPointerDown={(event) => {
                    event.stopPropagation();
                    setSelectedOverlayId(overlay.id);
                    if (overlay.type !== "text") {
                      setEditingTextId(null);
                    }
                    if (overlay.type !== "equation") {
                      setEditingEquationId(null);
                    }
                  }}
                >
                  <div
                    className={`h-full w-full overflow-hidden rounded ${
                      selected
                        ? "border border-indigo-400 shadow-sm ring-1 ring-indigo-200"
                        : "border border-transparent"
                    }`}
                    style={{ backgroundColor: baseBackground }}
                  >
                    {overlay.type === "text" ? (
                      isTextEditing ? (
                        <textarea
                          autoFocus
                          value={overlay.text}
                          onChange={(event) => {
                            const nextPage = updateOverlay(overlay.id, (item) => ({
                              ...item,
                              text: event.target.value,
                            }));
                            if (autosaveEnabled && nextPage) {
                              queueAutosave(nextPage);
                            }
                          }}
                          onPointerDown={(event) => {
                            event.stopPropagation();
                            setSelectedOverlayId(overlay.id);
                          }}
                          onBlur={() => {
                            setEditingTextId((prev) => (prev === overlay.id ? null : prev));
                          }}
                          className="h-full w-full resize-none border-0 bg-transparent px-2 py-1.5 outline-none"
                          style={{
                            fontFamily: overlay.style.fontFamily,
                            fontSize: `${Math.max(12, overlay.style.fontSize) * zoom}px`,
                            lineHeight: 1.3,
                            color: overlay.style.color,
                            fontWeight: overlay.style.bold ? 700 : 400,
                            fontStyle: overlay.style.italic ? "italic" : "normal",
                            textDecoration: textDecoration || "none",
                          }}
                          placeholder="Type your text..."
                        />
                      ) : (
                        <button
                          type="button"
                          className="flex h-full w-full items-start justify-start overflow-auto bg-transparent px-2 py-1.5 text-left"
                          onDoubleClick={(event) => {
                            event.stopPropagation();
                            setSelectedOverlayId(overlay.id);
                            setEditingTextId(overlay.id);
                          }}
                          onClick={(event) => {
                            event.stopPropagation();
                            setSelectedOverlayId(overlay.id);
                          }}
                        >
                          <div
                            className="w-full whitespace-pre-wrap break-words"
                            style={{
                              fontFamily: overlay.style.fontFamily,
                              fontSize: `${Math.max(12, overlay.style.fontSize) * zoom}px`,
                              lineHeight: 1.3,
                              color: overlay.style.color,
                              fontWeight: overlay.style.bold ? 700 : 400,
                              fontStyle: overlay.style.italic ? "italic" : "normal",
                              textDecoration: textDecoration || "none",
                              backgroundColor: overlay.style.highlight ? "rgba(254, 240, 138, 0.28)" : "transparent",
                            }}
                          >
                            {overlay.text || "Double-click to edit"}
                          </div>
                        </button>
                      )
                    ) : isEquationEditing ? (
                      <div className="flex h-full flex-col gap-1 bg-transparent p-2">
                        <textarea
                          autoFocus
                          value={overlay.text}
                          onChange={(event) => {
                            const nextPage = updateOverlay(overlay.id, (item) => ({
                              ...item,
                              text: event.target.value,
                            }));
                            if (autosaveEnabled && nextPage) {
                              queueAutosave(nextPage);
                            }
                          }}
                          onPointerDown={(event) => {
                            event.stopPropagation();
                            setSelectedOverlayId(overlay.id);
                          }}
                          onBlur={() => {
                            setEditingEquationId((prev) => (prev === overlay.id ? null : prev));
                          }}
                          className="h-full w-full resize-none border-0 bg-transparent px-2 py-1.5 outline-none"
                          style={{
                            fontFamily: overlay.style.fontFamily || "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                            color: overlay.style.color,
                            fontSize: `${Math.max(12, overlay.style.fontSize) * zoom}px`,
                            lineHeight: 1.3,
                            fontWeight: overlay.style.bold ? 700 : 400,
                            fontStyle: overlay.style.italic ? "italic" : "normal",
                            textDecoration: textDecoration || "none",
                            backgroundColor: overlay.style.highlight ? "rgba(254, 240, 138, 0.16)" : "transparent",
                          }}
                          placeholder="LaTeX (e.g., \\frac{a}{b})"
                        />
                      </div>
                    ) : (
                      <button
                        type="button"
                        className="flex h-full w-full items-center justify-center overflow-auto bg-transparent px-2 py-1 text-left"
                        onDoubleClick={(event) => {
                          event.stopPropagation();
                          setSelectedOverlayId(overlay.id);
                          setEditingEquationId(overlay.id);
                        }}
                        onClick={(event) => {
                          event.stopPropagation();
                          setSelectedOverlayId(overlay.id);
                        }}
                      >
                        {preview?.error ? (
                          <div className="text-xs text-red-600">{preview.error}</div>
                        ) : (
                          <div
                            className="max-w-full"
                            style={{
                              fontFamily: overlay.style.fontFamily,
                              color: overlay.style.color,
                              fontSize: `${Math.max(12, overlay.style.fontSize)}px`,
                              fontWeight: overlay.style.bold ? 700 : 400,
                              fontStyle: overlay.style.italic ? "italic" : "normal",
                              textDecoration: textDecoration || "none",
                              backgroundColor: overlay.style.highlight ? "rgba(254, 240, 138, 0.22)" : "transparent",
                              transform: `scale(${Math.max(0.6, zoom)})`,
                              transformOrigin: "center center",
                            }}
                            dangerouslySetInnerHTML={{ __html: preview?.html || "" }}
                          />
                        )}
                      </button>
                    )}
                  </div>

                  {selected ? (
                    <>
                      <button
                        className="absolute -top-2 -left-2 h-5 w-5 rounded-full border border-slate-200 bg-white text-slate-600 shadow hover:bg-slate-50"
                        onPointerDown={(event) => handleOverlayPointerDown(overlay, event)}
                        title="Move box"
                      >
                        <Move className="mx-auto h-3 w-3" />
                      </button>
                      <button
                        className="absolute -top-2 -right-2 h-5 w-5 rounded-full border border-red-200 bg-white text-red-600 shadow hover:bg-red-50"
                        onClick={() => handleOverlayDelete(overlay.id)}
                        title="Delete box"
                      >
                        <Trash2 className="mx-auto h-3 w-3" />
                      </button>
                      {isEditing ? (
                        <div className="absolute -top-8 right-5 flex items-center gap-1 rounded border border-slate-200 bg-white px-1.5 py-1 shadow">
                          <button
                            className="rounded px-1.5 py-0.5 text-[10px] font-semibold text-slate-600 hover:bg-slate-100"
                            onClick={(event) => {
                              event.stopPropagation();
                              if (overlay.type === "text") {
                                setEditingTextId((prev) => (prev === overlay.id ? null : prev));
                              } else if (overlay.type === "equation") {
                                setEditingEquationId((prev) => (prev === overlay.id ? null : prev));
                              }
                            }}
                            title="Finish editing"
                          >
                            Done
                          </button>
                        </div>
                      ) : null}
                      <button
                        type="button"
                        className="absolute -bottom-2 -right-2 h-4 w-4 cursor-se-resize rounded border border-indigo-300 bg-white shadow"
                        onPointerDown={(event) => handleOverlayResizePointerDown(overlay, event)}
                        title="Resize box"
                      />
                    </>
                  ) : null}
                </div>
              );
            })}
            {tool === "eraser" && eraserCursor.visible && (
              <div
                className="pointer-events-none absolute rounded-full border border-slate-800/70 bg-slate-800/10"
                style={{
                  left: `${eraserCursor.x * zoom}px`,
                  top: `${eraserCursor.y * zoom}px`,
                  width: `${Math.max(10, eraserCursor.size * zoom)}px`,
                  height: `${Math.max(10, eraserCursor.size * zoom)}px`,
                  transform: "translate(-50%, -50%)",
                }}
              />
            )}
          </div>
          <div className="mt-3 flex gap-2 flex-wrap">
            {pages.map((page) => (
              <button
                key={page.page_index}
                onClick={() => setCurrentPageIndex(page.page_index)}
                className={`px-3 py-1.5 rounded-lg text-xs border ${
                  page.page_index === currentPageIndex
                    ? "bg-indigo-50 border-indigo-300 text-indigo-700"
                    : "bg-white border-slate-200 text-slate-600"
                }`}
              >
                Page {page.page_index + 1} ({page.strokes.length} strokes, {page.overlays.length} boxes)
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="w-[360px] bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-2xl shadow-sm flex flex-col overflow-hidden">
        <div className="p-4 border-b border-slate-100 dark:border-slate-700">
          <h2 className="font-bold text-slate-900 dark:text-slate-100">OCR Review</h2>
          <p className="text-xs text-slate-500 mt-1">
            Confidence: {quality.ocr_confidence !== undefined ? quality.ocr_confidence.toFixed(3) : "--"} | Needs
            review: {quality.needs_review ? "Yes" : "No"}
          </p>
          {ocrDiagnostics.length > 0 && (
            <div className="mt-2 space-y-1">
              {ocrDiagnostics.slice(0, 2).map((diag) => (
                <p
                  key={`diag-${diag.page_index}-${diag.provider}`}
                  className={`text-[11px] ${
                    diag.used_fallback ? "text-amber-700" : "text-emerald-700"
                  }`}
                >
                  P{diag.page_index + 1}: {diag.used_fallback ? "fallback" : "vision"}{" "}
                  {diag.status_code ? `(HTTP ${diag.status_code})` : ""}{" "}
                  {diag.message ? `- ${diag.message}` : ""}
                </p>
              ))}
            </div>
          )}
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {reviewIssues.length === 0 && structuredBlocks.length === 0 && (
            <div className="text-sm text-slate-500">Run OCR pipeline to inspect blocks.</div>
          )}
          {structuredBlocks.map((block) => {
            const edit = reviewEdits[block.id] || { text: block.normalized_text, block_type: block.block_type };
            const hasIssue = reviewIssues.some((issue) => issue.block_id === block.id);
            return (
              <div
                key={block.id}
                className={`rounded-xl border p-3 ${hasIssue ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-slate-50"}`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px] uppercase tracking-wide text-slate-500">
                    {block.id} · Page {block.page_index + 1}
                  </span>
                  <select
                    value={edit.block_type}
                    onChange={(event) =>
                      setReviewEdits((prev) => ({
                        ...prev,
                        [block.id]: { ...edit, block_type: event.target.value as StructuredBlock["block_type"] },
                      }))
                    }
                    className="text-xs border rounded px-1.5 py-1 bg-white"
                  >
                    <option value="heading">heading</option>
                    <option value="paragraph">paragraph</option>
                    <option value="equation">equation</option>
                    <option value="diagram">diagram</option>
                    <option value="shape-note">shape-note</option>
                  </select>
                </div>
                <textarea
                  value={edit.text}
                  onChange={(event) =>
                    setReviewEdits((prev) => ({
                      ...prev,
                      [block.id]: { ...edit, text: event.target.value },
                    }))
                  }
                  rows={3}
                  className="w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-sm"
                />
                {hasIssue && (
                  <p className="text-[11px] text-amber-700 mt-2">
                    {reviewIssues.find((issue) => issue.block_id === block.id)?.reason}
                  </p>
                )}
              </div>
            );
          })}
        </div>
        <div className="p-3 border-t border-slate-100 dark:border-slate-700 space-y-1">
          {notice && <div className="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-2 py-1.5">{notice}</div>}
          {error && <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1.5">{error}</div>}
        </div>
      </div>
    </div>
  );
}
