import type { SlideElement, SlideProDeck } from "@/types/slidePro";

export interface PptColorSpec {
  color: string;
  transparency?: number;
}

export interface ParsedColor {
  hex: string;
  alpha: number;
}

export interface CanvasSize {
  width: number;
  height: number;
}

export interface PptTransform {
  toX: (value: number) => number;
  toY: (value: number) => number;
  toW: (value: number) => number;
  toH: (value: number) => number;
}

export const OFFICE_FONT_MAP: Record<string, string> = {
  sora: "Aptos",
  manrope: "Calibri",
  "ibm plex sans": "Calibri",
  "space grotesk": "Aptos",
  "source sans 3": "Calibri",
  fraunces: "Georgia",
  "playfair display": "Cambria",
};

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

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
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

function normalizeHex(raw: string, fallback: string): ParsedColor {
  const trimmed = raw.trim().replace(/^#/, "");
  const fallbackClean = fallback.trim().replace(/^#/, "");
  if (/^[0-9a-fA-F]{8}$/.test(trimmed)) {
    const rgb = trimmed.slice(0, 6).toUpperCase();
    const alphaHex = trimmed.slice(6, 8);
    const alpha = clamp(parseInt(alphaHex, 16) / 255, 0, 1);
    return { hex: rgb, alpha };
  }
  if (/^[0-9a-fA-F]{6}$/.test(trimmed)) {
    return { hex: trimmed.toUpperCase(), alpha: 1 };
  }
  if (/^[0-9a-fA-F]{3}$/.test(trimmed)) {
    const hex = trimmed
      .split("")
      .map((ch) => `${ch}${ch}`)
      .join("")
      .toUpperCase();
    return { hex, alpha: 1 };
  }
  const safe = /^[0-9a-fA-F]{6}$/.test(fallbackClean) ? fallbackClean.toUpperCase() : "0F172A";
  return { hex: safe, alpha: 1 };
}

function parseColor(value: unknown, fallback: string): ParsedColor {
  return normalizeHex(asString(value, fallback), fallback);
}

function hexToRgb(hex: string): [number, number, number] {
  const normalized = hex.replace(/^#/, "");
  const safe = /^[0-9A-Fa-f]{6}$/.test(normalized) ? normalized : "0F172A";
  return [
    Number.parseInt(safe.slice(0, 2), 16),
    Number.parseInt(safe.slice(2, 4), 16),
    Number.parseInt(safe.slice(4, 6), 16),
  ];
}

export function resolveOfficeFont(fontName: string, fallback: "title" | "body"): string {
  const key = fontName.trim().toLowerCase();
  if (key && OFFICE_FONT_MAP[key]) return OFFICE_FONT_MAP[key];
  return fallback === "title" ? "Aptos Display" : "Aptos";
}

export function previewFontFamily(deck: SlideProDeck, fallback: "title" | "body"): string {
  const raw = fallback === "title" ? deck.theme.fonts.title : deck.theme.fonts.body;
  const office = resolveOfficeFont(raw, fallback);
  return `"${office}", "Segoe UI", "Arial", sans-serif`;
}

export function isTitleElement(element: SlideElement): boolean {
  return element.id.endsWith("_title");
}

export function colorToPpt(value: unknown, fallback: string): PptColorSpec {
  const { hex, alpha } = parseColor(value, fallback);
  const transparency = alpha >= 0.999 ? undefined : Math.round((1 - alpha) * 100);
  return transparency !== undefined ? { color: hex, transparency } : { color: hex };
}

export function resolveFillColorForPpt(
  value: unknown,
  fallback: string,
  fillOpacity?: unknown,
): PptColorSpec {
  const parsed = parseColor(value, fallback);
  const opacityRaw = asNumber(fillOpacity, Number.NaN);
  const opacity = Number.isFinite(opacityRaw) ? clamp(opacityRaw, 0, 1) : 1;
  const effectiveAlpha = clamp(parsed.alpha * opacity, 0, 1);
  const transparency = effectiveAlpha >= 0.999 ? undefined : Math.round((1 - effectiveAlpha) * 100);
  return transparency !== undefined ? { color: parsed.hex, transparency } : { color: parsed.hex };
}

export function colorToCss(value: unknown, fallback: string, fillOpacity?: unknown): string {
  const parsed = parseColor(value, fallback);
  const opacityRaw = asNumber(fillOpacity, Number.NaN);
  const opacity = Number.isFinite(opacityRaw) ? clamp(opacityRaw, 0, 1) : 1;
  const effectiveAlpha = clamp(parsed.alpha * opacity, 0, 1);
  const [r, g, b] = hexToRgb(parsed.hex);
  if (effectiveAlpha >= 0.999) {
    return `#${parsed.hex}`;
  }
  const roundedAlpha = Math.round(effectiveAlpha * 1000) / 1000;
  return `rgba(${r}, ${g}, ${b}, ${roundedAlpha})`;
}

export function createCanvasToPptTransform(
  size: CanvasSize,
  pptWidth = 13.333,
  pptHeight = 7.5,
): PptTransform {
  const widthRatio = pptWidth / Math.max(1, size.width);
  const heightRatio = pptHeight / Math.max(1, size.height);
  const toX = (value: number) => value * widthRatio;
  const toY = (value: number) => value * heightRatio;
  return {
    toX,
    toY,
    toW: toX,
    toH: toY,
  };
}

export function resolveLineHeight(element: SlideElement): number {
  const fallback = element.type === "bullets" ? 1.28 : 1.22;
  return clamp(asNumber(element.style?.lineHeight, fallback), 1.0, 1.8);
}

export function resolveBulletSpacingPt(element: SlideElement): number {
  const fontSize = asNumber(element.style?.fontSize, 24);
  const lineHeight = resolveLineHeight(element);
  const extra = Math.max(0, (lineHeight - 1.0) * fontSize * 0.58);
  return clamp(Math.round(extra), 0, 12);
}

function wrapSingleLine(line: string, charsPerLine: number): string[] {
  const compact = String(line || "").trim();
  if (!compact) return [];
  if (compact.length <= charsPerLine) return [compact];

  const words = compact.split(/\s+/).filter(Boolean);
  const wrapped: string[] = [];
  let current = "";
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length <= charsPerLine) {
      current = candidate;
      continue;
    }
    if (current) wrapped.push(current);
    if (word.length <= charsPerLine) {
      current = word;
      continue;
    }
    // Hard-wrap long tokens to keep deterministic geometry.
    let cursor = 0;
    while (cursor < word.length) {
      wrapped.push(word.slice(cursor, cursor + charsPerLine));
      cursor += charsPerLine;
    }
    current = "";
  }
  if (current) wrapped.push(current);
  return wrapped;
}

export function resolveWrappedTextLines(element: SlideElement, fontSizeOverride?: number): string[] {
  const rawLines = toSingleText(element.content).split("\n");
  const fontSize = asNumber(fontSizeOverride, asNumber(element.style?.fontSize, element.type === "text" ? 36 : 24));
  const charsPerLine = Math.max(12, Math.floor(element.box.w / Math.max(7, fontSize * 0.53)));
  const wrapped: string[] = [];
  for (const line of rawLines) {
    const chunks = wrapSingleLine(line, charsPerLine);
    if (chunks.length === 0) {
      if (wrapped.length === 0) wrapped.push("");
      continue;
    }
    wrapped.push(...chunks);
  }
  return wrapped.length > 0 ? wrapped : [""];
}

export interface WrappedBulletLine {
  text: string;
  bullet: boolean;
}

export function resolveWrappedBulletLines(element: SlideElement, fontSizeOverride?: number): WrappedBulletLine[] {
  const sourceLines = toLineArray(element.content);
  const fontSize = asNumber(fontSizeOverride, asNumber(element.style?.fontSize, 24));
  const charsPerLine = Math.max(12, Math.floor(element.box.w / Math.max(7, fontSize * 0.53)));
  const output: WrappedBulletLine[] = [];
  for (const line of sourceLines) {
    const chunks = wrapSingleLine(line, charsPerLine);
    if (chunks.length === 0) continue;
    chunks.forEach((chunk, idx) => {
      output.push({ text: chunk, bullet: idx === 0 });
    });
  }
  return output;
}

export function estimateWrappedLineCount(element: SlideElement): number {
  const fontSize = asNumber(element.style?.fontSize, element.type === "text" ? 36 : 24);
  if (element.type === "bullets") {
    return resolveWrappedBulletLines(element, fontSize).length;
  }
  return resolveWrappedTextLines(element, fontSize).filter((line) => line.trim().length > 0).length;
}

function estimateTextOverflowAtSize(element: SlideElement, fontSize: number): boolean {
  const lineHeight = resolveLineHeight({ ...element, style: { ...element.style, fontSize } });
  const capacity = element.box.h / Math.max(10, fontSize * lineHeight);
  const wrapped = estimateWrappedLineCount({ ...element, style: { ...element.style, fontSize } });
  return wrapped > capacity - 0.25;
}

export function estimateTextOverflow(element: SlideElement): boolean {
  if (!(element.type === "text" || element.type === "bullets" || element.type === "equation")) {
    return false;
  }
  const originalSize = asNumber(element.style?.fontSize, element.type === "text" ? 36 : 24);
  const textFit = asString(element.style?.textFit, "shrink");
  if (textFit === "none") {
    return estimateTextOverflowAtSize(element, originalSize);
  }
  if (!estimateTextOverflowAtSize(element, originalSize)) return false;
  let trialSize = originalSize;
  let guard = 0;
  while (trialSize > 14 && guard < 14) {
    trialSize -= 1;
    guard += 1;
    if (!estimateTextOverflowAtSize(element, trialSize)) {
      return false;
    }
  }
  return true;
}

function chartLabelsFromElement(element: SlideElement): string[] {
  const labels = Array.isArray(element.data?.labels) ? element.data.labels : [];
  return labels.map((item) => String(item || "").trim()).filter(Boolean);
}

function chartValuesFromElement(element: SlideElement): number[] {
  const series = Array.isArray(element.data?.series) ? element.data.series : [];
  const first = (series[0] || {}) as Record<string, unknown>;
  const valuesRaw = Array.isArray(first.values) ? first.values : [];
  return valuesRaw
    .map((item) => asNumber(item, Number.NaN))
    .filter((value) => Number.isFinite(value))
    .map((value) => Math.max(0, value));
}

function safeLabel(label: string): string {
  const compact = label.replace(/[\r\n\t]+/g, " ").trim();
  const normalized = compact.length > 12 ? `${compact.slice(0, 11)}…` : compact;
  return normalized.replace(/[<>&"]/g, " ");
}

function encodeSvgDataUrl(svg: string): string {
  try {
    const utf8 = encodeURIComponent(svg).replace(
      /%([0-9A-F]{2})/g,
      (_match, group: string) => String.fromCharCode(Number.parseInt(group, 16)),
    );
    if (typeof btoa === "function") {
      return `data:image/svg+xml;base64,${btoa(utf8)}`;
    }
  } catch {
    // Fall through to utf8 data-url fallback.
  }
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

export function hasGroundedChartData(element: SlideElement): boolean {
  if (element.type !== "chart") return false;
  if (element.data?.grounded === false) return false;
  const values = chartValuesFromElement(element);
  return values.length > 0;
}

export function buildChartSvgDataUrl(
  element: SlideElement,
  opts?: { accent?: string; foreground?: string; muted?: string; background?: string },
): string | null {
  if (!hasGroundedChartData(element)) return null;
  const values = chartValuesFromElement(element);
  if (values.length === 0) return null;
  const labels = chartLabelsFromElement(element);
  const chartType = asString(element.style?.chartType, "bar").toLowerCase();
  const accent = colorToPpt(opts?.accent || element.style?.color, "#0EA5E9").color;
  const fg = colorToPpt(opts?.foreground, "#0F172A").color;
  const muted = colorToPpt(opts?.muted, "#475569").color;
  const bg = colorToPpt(opts?.background, "#FFFFFF").color;

  const viewW = 1000;
  const viewH = 560;
  const leftPad = 88;
  const rightPad = 34;
  const topPad = 28;
  const bottomPad = 104;
  const plotW = viewW - leftPad - rightPad;
  const plotH = viewH - topPad - bottomPad;
  const maxValue = Math.max(1, ...values);
  const roundedTop = Math.max(5, Math.ceil(maxValue / 5) * 5);
  const gridSteps = 5;
  const gridLines: string[] = [];
  for (let i = 0; i <= gridSteps; i += 1) {
    const y = topPad + (plotH / gridSteps) * i;
    const value = Math.round(((gridSteps - i) * roundedTop) / gridSteps);
    gridLines.push(
      `<line x1="${leftPad}" y1="${y}" x2="${leftPad + plotW}" y2="${y}" stroke="#D6DFEA" stroke-width="1"/>`,
    );
    gridLines.push(
      `<text x="${leftPad - 10}" y="${y + 5}" text-anchor="end" font-size="19" fill="#${muted}" font-family="Aptos, Arial, sans-serif">${value}</text>`,
    );
  }

  const n = values.length;
  const xStep = n <= 1 ? plotW : plotW / (n - 1);
  const barSlot = n <= 1 ? plotW : plotW / n;
  const barWidth = Math.max(22, Math.min(78, barSlot * 0.58));
  const points = values.map((value, idx) => {
    const x = n <= 1 ? leftPad + plotW / 2 : leftPad + xStep * idx;
    const y = topPad + plotH - (value / roundedTop) * plotH;
    return { x, y, value };
  });

  const xLabels = points
    .map((point, idx) => {
      const text = safeLabel(labels[idx] || `M${idx + 1}`);
      return (
        `<text x="${point.x}" y="${viewH - 36}" text-anchor="middle" font-size="20" fill="#${fg}" ` +
        `font-family="Aptos, Arial, sans-serif" transform="rotate(-34 ${point.x} ${viewH - 36})">${text}</text>`
      );
    })
    .join("");

  let seriesSvg = "";
  if (chartType === "line" || chartType === "area") {
    const coords = points.map((point) => `${point.x},${point.y}`).join(" ");
    if (chartType === "area") {
      const areaPoints = `${leftPad},${topPad + plotH} ${coords} ${leftPad + plotW},${topPad + plotH}`;
      seriesSvg += `<polygon points="${areaPoints}" fill="#${accent}" fill-opacity="0.18" stroke="none"/>`;
    }
    seriesSvg += `<polyline points="${coords}" fill="none" stroke="#${accent}" stroke-width="4"/>`;
    seriesSvg += points
      .map((point) => `<circle cx="${point.x}" cy="${point.y}" r="5" fill="#${accent}"/>`)
      .join("");
  } else {
    seriesSvg = points
      .map((point) => {
        const x = point.x - barWidth / 2;
        const h = topPad + plotH - point.y;
        return `<rect x="${x}" y="${point.y}" width="${barWidth}" height="${h}" rx="5" fill="#${accent}" />`;
      })
      .join("");
  }

  const svg = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${viewW}" height="${viewH}" viewBox="0 0 ${viewW} ${viewH}">`,
    `<rect x="0" y="0" width="${viewW}" height="${viewH}" rx="14" fill="#${bg}"/>`,
    ...gridLines,
    `<line x1="${leftPad}" y1="${topPad + plotH}" x2="${leftPad + plotW}" y2="${topPad + plotH}" stroke="#94A3B8" stroke-width="1.2"/>`,
    seriesSvg,
    xLabels,
    "</svg>",
  ].join("");
  return encodeSvgDataUrl(svg);
}

export function withPptxFit(deck: SlideProDeck): SlideProDeck {
  const next = structuredClone(deck) as SlideProDeck;
  for (const slide of next.slides) {
    for (const element of slide.elements) {
      if (!(element.type === "text" || element.type === "bullets" || element.type === "equation")) {
        continue;
      }
      if (element.style?.textFit === "none") continue;
      let fontSize = asNumber(element.style?.fontSize, element.type === "text" ? 36 : 24);
      let guard = 0;
      while (estimateTextOverflow({ ...element, style: { ...element.style, fontSize } }) && fontSize > 14 && guard < 14) {
        fontSize -= 1;
        guard += 1;
      }
      element.style = { ...element.style, fontSize };
    }
  }
  return next;
}
