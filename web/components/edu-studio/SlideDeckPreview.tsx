"use client";

import { useEffect, useMemo, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

import { processLatexContent } from "@/lib/latex";
import { DeckTheme, SlideData, SlideDeckData } from "@/types/eduStudio";

interface SlideDeckPreviewProps {
  deck: SlideDeckData;
  onSlidesReady?: (slides: HTMLDivElement[]) => void;
}

function normalizeDeckTheme(theme?: Partial<DeckTheme>): DeckTheme {
  const fallbackFont = "Space Grotesk, Manrope, Avenir Next, Segoe UI, sans-serif";
  return {
    palette: {
      background: theme?.palette?.background || "#F8FAFC",
      foreground: theme?.palette?.foreground || "#0F172A",
      accent: theme?.palette?.accent || "#0EA5E9",
      muted: theme?.palette?.muted || "#475569",
    },
    typography: {
      font_family: theme?.typography?.font_family || fallbackFont,
      title_scale: theme?.typography?.title_scale || "2rem",
      body_scale: theme?.typography?.body_scale || "1rem",
    },
    visual_style: theme?.visual_style || "clean-academic",
    ratio: theme?.ratio || "16:9",
  };
}

function ratioToCss(ratio: string): string {
  const parts = ratio.split(":").map((item) => Number(item.trim()));
  if (parts.length === 2 && parts.every((n) => Number.isFinite(n) && n > 0)) {
    return `${parts[0]} / ${parts[1]}`;
  }
  return "16 / 9";
}

function MarkdownText({ content, className = "" }: { content: string; className?: string }) {
  const latexClasses =
    "[&_.katex]:text-inherit [&_.katex]:leading-tight [&_.katex-display]:my-1 [&_.katex-display]:overflow-x-auto";
  return (
    <div className={`${latexClasses} ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
        {processLatexContent(content)}
      </ReactMarkdown>
    </div>
  );
}

function splitInTwo<T>(items: T[]): [T[], T[]] {
  const mid = Math.ceil(items.length / 2);
  return [items.slice(0, mid), items.slice(mid)];
}

function hexToRgb(hex: string): [number, number, number] | null {
  const normalized = hex.trim().replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(normalized)) return null;
  const num = Number.parseInt(normalized, 16);
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
}

function withAlpha(hex: string, alpha: number): string {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  const safeAlpha = Math.min(1, Math.max(0, alpha));
  return `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${safeAlpha})`;
}

function xmlEscape(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function toSvgDataUrl(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function trimLabel(value: string, max = 24): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= max) return normalized;
  return `${normalized.slice(0, max - 3).trim()}...`;
}

function buildIllustrationSvg(slide: SlideData, theme: DeckTheme): string {
  const accent = theme.palette.accent;
  const foreground = theme.palette.foreground;
  const muted = theme.palette.muted;
  const background = theme.palette.background;
  const points = Array.isArray(slide.key_points) ? slide.key_points : [];
  const labels = points.slice(0, 4).map((point, idx) => trimLabel(point || `Point ${idx + 1}`, 28));
  const fallbackLabels = ["Context", "Mechanism", "Outcome", "Action"];
  const textLabels = labels.length > 0 ? labels : fallbackLabels;

  if (slide.layout_hint === "timeline") {
    const timelineLabels = [...textLabels, ...fallbackLabels].slice(0, 4);
    return `
<svg xmlns="http://www.w3.org/2000/svg" width="960" height="520" viewBox="0 0 960 520">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="${withAlpha(accent, 0.15)}" />
      <stop offset="100%" stop-color="${withAlpha(background, 1)}" />
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="960" height="520" rx="28" fill="url(#bg)" />
  <line x1="120" y1="260" x2="840" y2="260" stroke="${withAlpha(muted, 0.7)}" stroke-width="6"/>
  ${timelineLabels
    .map((label, index) => {
      const x = 160 + index * 220;
      return `
    <circle cx="${x}" cy="260" r="28" fill="${withAlpha(accent, 0.95)}" />
    <text x="${x}" y="350" text-anchor="middle" font-size="28" font-family="Segoe UI, Arial, sans-serif" fill="${foreground}" font-weight="600">${xmlEscape(label)}</text>
    <text x="${x}" y="265" text-anchor="middle" font-size="24" font-family="Segoe UI, Arial, sans-serif" fill="${background}" font-weight="700">${index + 1}</text>
`;
    })
    .join("")}
</svg>
`.trim();
  }

  if (slide.layout_hint === "comparison") {
    const [leftRaw, rightRaw] = splitInTwo(textLabels);
    const left = leftRaw.length ? leftRaw : fallbackLabels.slice(0, 2);
    const right = rightRaw.length ? rightRaw : fallbackLabels.slice(2, 4);
    return `
<svg xmlns="http://www.w3.org/2000/svg" width="960" height="520" viewBox="0 0 960 520">
  <rect x="0" y="0" width="960" height="520" rx="28" fill="${withAlpha(background, 1)}" />
  <rect x="54" y="62" width="400" height="396" rx="24" fill="${withAlpha(accent, 0.12)}" stroke="${withAlpha(accent, 0.55)}" stroke-width="3" />
  <rect x="506" y="62" width="400" height="396" rx="24" fill="${withAlpha(muted, 0.1)}" stroke="${withAlpha(muted, 0.45)}" stroke-width="3" />
  <text x="88" y="112" font-size="28" font-family="Segoe UI, Arial, sans-serif" fill="${foreground}" font-weight="700">Axis A</text>
  <text x="540" y="112" font-size="28" font-family="Segoe UI, Arial, sans-serif" fill="${foreground}" font-weight="700">Axis B</text>
  ${left
    .slice(0, 3)
    .map(
      (label, idx) => `
    <text x="88" y="${172 + idx * 84}" font-size="24" font-family="Segoe UI, Arial, sans-serif" fill="${foreground}">• ${xmlEscape(label)}</text>
`,
    )
    .join("")}
  ${right
    .slice(0, 3)
    .map(
      (label, idx) => `
    <text x="540" y="${172 + idx * 84}" font-size="24" font-family="Segoe UI, Arial, sans-serif" fill="${foreground}">• ${xmlEscape(label)}</text>
`,
    )
    .join("")}
</svg>
`.trim();
  }

  if (slide.layout_hint === "equation") {
    const equationLabel = trimLabel(points[0] || slide.objective || "Model Equation", 36);
    return `
<svg xmlns="http://www.w3.org/2000/svg" width="960" height="520" viewBox="0 0 960 520">
  <defs>
    <linearGradient id="eqbg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="${withAlpha(accent, 0.2)}" />
      <stop offset="100%" stop-color="${withAlpha(background, 1)}" />
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="960" height="520" rx="28" fill="url(#eqbg)" />
  <rect x="130" y="118" width="700" height="176" rx="22" fill="${withAlpha(background, 0.92)}" stroke="${withAlpha(accent, 0.55)}" stroke-width="3" />
  <text x="480" y="196" text-anchor="middle" font-size="30" font-family="Segoe UI, Arial, sans-serif" fill="${foreground}" font-weight="700">${xmlEscape(equationLabel)}</text>
  <text x="480" y="242" text-anchor="middle" font-size="24" font-family="Segoe UI, Arial, sans-serif" fill="${muted}">Analyze relation, stability, and impact</text>
  <circle cx="220" cy="390" r="34" fill="${withAlpha(accent, 0.9)}" />
  <circle cx="740" cy="390" r="34" fill="${withAlpha(accent, 0.55)}" />
  <line x1="254" y1="390" x2="706" y2="390" stroke="${withAlpha(foreground, 0.4)}" stroke-width="4"/>
</svg>
`.trim();
  }

  const genericLabels = [...textLabels, ...fallbackLabels].slice(0, 3);
  return `
<svg xmlns="http://www.w3.org/2000/svg" width="960" height="520" viewBox="0 0 960 520">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="${withAlpha(accent, 0.2)}" />
      <stop offset="100%" stop-color="${withAlpha(background, 1)}" />
    </linearGradient>
  </defs>
  <rect x="0" y="0" width="960" height="520" rx="28" fill="url(#g)" />
  <rect x="80" y="96" width="800" height="328" rx="24" fill="${withAlpha(background, 0.92)}" stroke="${withAlpha(muted, 0.35)}" stroke-width="2" />
  <circle cx="160" cy="170" r="18" fill="${withAlpha(accent, 0.95)}" />
  <circle cx="206" cy="170" r="18" fill="${withAlpha(accent, 0.7)}" />
  <circle cx="252" cy="170" r="18" fill="${withAlpha(accent, 0.45)}" />
  ${genericLabels
    .map(
      (label, idx) => `
  <rect x="140" y="${218 + idx * 88}" width="680" height="58" rx="14" fill="${withAlpha(accent, 0.09)}" />
  <text x="170" y="${255 + idx * 88}" font-size="24" font-family="Segoe UI, Arial, sans-serif" fill="${foreground}" font-weight="600">${xmlEscape(label)}</text>
`,
    )
    .join("")}
</svg>
`.trim();
}

function SlideIllustration({
  slide,
  theme,
  preset,
}: {
  slide: SlideData;
  theme: DeckTheme;
  preset: VisualPreset;
}) {
  const svgUrl = useMemo(() => toSvgDataUrl(buildIllustrationSvg(slide, theme)), [slide, theme]);
  const promptText = (slide.visual_prompt || slide.visual_hint || "").trim();

  return (
    <div
      className="min-h-[220px] rounded-2xl border p-3 flex flex-col gap-2"
      style={{ background: preset.surfaceSoft, borderColor: preset.border }}
    >
      <div className="text-[11px] uppercase tracking-[0.2em] font-semibold" style={{ color: theme.palette.accent }}>
        Illustration Preview
      </div>
      <img
        data-testid="slide-illustration"
        src={svgUrl}
        alt={`Illustration for ${slide.title}`}
        className="w-full rounded-xl border min-h-[170px] object-contain"
        style={{ borderColor: preset.border, background: withAlpha(theme.palette.background, 0.7) }}
      />
      <div className="text-[11px] leading-relaxed" style={{ color: withAlpha(theme.palette.foreground, 0.78) }}>
        {promptText || "Use visual cues to reinforce the learning objective."}
      </div>
    </div>
  );
}

interface VisualPreset {
  titleFont: string;
  bodyFont: string;
  backdrop: string;
  texture: string;
  surface: string;
  surfaceSoft: string;
  border: string;
  chipBg: string;
  chipBorder: string;
}

function getVisualPreset(theme: DeckTheme): VisualPreset {
  const style = theme.visual_style.toLowerCase();
  if (style.includes("executive")) {
    return {
      titleFont: "Fraunces, Cambria, Georgia, serif",
      bodyFont: "Manrope, Avenir Next, Segoe UI, sans-serif",
      backdrop: `linear-gradient(135deg, ${withAlpha(theme.palette.background, 0.98)} 0%, ${withAlpha(theme.palette.accent, 0.16)} 100%)`,
      texture: `radial-gradient(circle at 16% 18%, ${withAlpha(theme.palette.accent, 0.2)} 0%, transparent 56%)`,
      surface: withAlpha("#FFFFFF", 0.88),
      surfaceSoft: withAlpha("#FFFFFF", 0.66),
      border: withAlpha(theme.palette.foreground, 0.16),
      chipBg: withAlpha(theme.palette.accent, 0.16),
      chipBorder: withAlpha(theme.palette.accent, 0.36),
    };
  }
  if (style.includes("story")) {
    return {
      titleFont: "Merriweather, Cambria, Georgia, serif",
      bodyFont: "Source Sans 3, Nunito Sans, Segoe UI, sans-serif",
      backdrop: `linear-gradient(132deg, ${withAlpha(theme.palette.background, 0.98)} 0%, ${withAlpha("#D97706", 0.14)} 68%, ${withAlpha(theme.palette.accent, 0.2)} 100%)`,
      texture: `radial-gradient(circle at 84% 12%, ${withAlpha("#F59E0B", 0.22)} 0%, transparent 58%)`,
      surface: withAlpha("#FFFFFF", 0.84),
      surfaceSoft: withAlpha("#FFFFFF", 0.58),
      border: withAlpha(theme.palette.foreground, 0.18),
      chipBg: withAlpha("#F59E0B", 0.16),
      chipBorder: withAlpha("#D97706", 0.35),
    };
  }
  if (style.includes("data")) {
    return {
      titleFont: "Sora, Montserrat, Segoe UI, sans-serif",
      bodyFont: "IBM Plex Sans, Manrope, Segoe UI, sans-serif",
      backdrop: `linear-gradient(128deg, ${withAlpha("#F8FAFC", 0.98)} 0%, ${withAlpha("#0EA5E9", 0.1)} 54%, ${withAlpha(theme.palette.accent, 0.14)} 100%)`,
      texture: `radial-gradient(circle at 90% 84%, ${withAlpha("#06B6D4", 0.2)} 0%, transparent 60%)`,
      surface: withAlpha("#FFFFFF", 0.86),
      surfaceSoft: withAlpha("#FFFFFF", 0.62),
      border: withAlpha(theme.palette.foreground, 0.18),
      chipBg: withAlpha("#0EA5E9", 0.14),
      chipBorder: withAlpha("#0EA5E9", 0.36),
    };
  }
  if (style.includes("chalk")) {
    return {
      titleFont: "Bricolage Grotesque, Space Grotesk, Segoe UI, sans-serif",
      bodyFont: "DM Sans, Manrope, Segoe UI, sans-serif",
      backdrop: `linear-gradient(145deg, ${withAlpha("#0B1324", 1)} 0%, ${withAlpha("#0F172A", 0.96)} 44%, ${withAlpha("#155E75", 0.45)} 100%)`,
      texture: `radial-gradient(circle at 20% 14%, ${withAlpha("#22D3EE", 0.18)} 0%, transparent 54%)`,
      surface: withAlpha("#0F172A", 0.64),
      surfaceSoft: withAlpha("#1E293B", 0.52),
      border: withAlpha("#E2E8F0", 0.22),
      chipBg: withAlpha("#22D3EE", 0.2),
      chipBorder: withAlpha("#22D3EE", 0.42),
    };
  }

  return {
    titleFont: "Sora, Space Grotesk, Avenir Next, Segoe UI, sans-serif",
    bodyFont: "Manrope, Source Sans 3, Segoe UI, sans-serif",
    backdrop: `linear-gradient(140deg, ${withAlpha(theme.palette.background, 0.98)} 0%, ${withAlpha(theme.palette.accent, 0.15)} 100%)`,
    texture: `radial-gradient(circle at 86% 18%, ${withAlpha(theme.palette.accent, 0.18)} 0%, transparent 56%)`,
    surface: withAlpha("#FFFFFF", 0.86),
    surfaceSoft: withAlpha("#FFFFFF", 0.62),
    border: withAlpha(theme.palette.foreground, 0.16),
    chipBg: withAlpha(theme.palette.accent, 0.14),
    chipBorder: withAlpha(theme.palette.accent, 0.34),
  };
}

function SlideBody({
  slide,
  theme,
  preset,
}: {
  slide: SlideData;
  theme: DeckTheme;
  preset: VisualPreset;
}) {
  const keyPoints = Array.isArray(slide.key_points) ? slide.key_points : [];
  const points = keyPoints.length ? keyPoints : [slide.objective];
  const accent = theme.palette.accent;
  const foreground = theme.palette.foreground;
  const muted = theme.palette.muted;

  if (slide.layout_hint === "title") {
    return (
      <div className="space-y-4">
        <MarkdownText
          content={slide.objective}
          className="text-[1.18rem] leading-relaxed [&_p]:m-0"
        />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {points.slice(0, 4).map((point, index) => (
            <div
              key={`${point}-${index}`}
              className="rounded-2xl p-3 border shadow-sm"
              style={{
                background: preset.surface,
                borderColor: preset.border,
                color: foreground,
              }}
            >
              <div
                className="inline-flex items-center justify-center text-[11px] font-bold rounded-full px-2 py-0.5 mb-2"
                style={{ background: preset.chipBg, border: `1px solid ${preset.chipBorder}`, color: accent }}
              >
                Focus {index + 1}
              </div>
              <MarkdownText content={point} className="text-[0.95rem] [&_p]:m-0 leading-relaxed" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (slide.layout_hint === "comparison") {
    const [left, right] = splitInTwo(points);
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div
          className="rounded-2xl border p-4 shadow-sm"
          style={{ background: preset.surface, borderColor: preset.border }}
        >
          <div className="text-xs uppercase tracking-[0.2em] font-semibold mb-3" style={{ color: accent }}>
            Axis A
          </div>
          <ul className="space-y-2 list-disc pl-4 text-[0.95rem]">
            {left.map((point, index) => (
              <li key={`${point}-${index}`}>
                <MarkdownText content={point} className="[&_p]:m-0" />
              </li>
            ))}
          </ul>
        </div>
        <div
          className="rounded-2xl border p-4 shadow-sm"
          style={{ background: preset.surfaceSoft, borderColor: preset.border }}
        >
          <div className="text-xs uppercase tracking-[0.2em] font-semibold mb-3" style={{ color: accent }}>
            Axis B
          </div>
          <ul className="space-y-2 list-disc pl-4 text-[0.95rem]">
            {right.map((point, index) => (
              <li key={`${point}-${index}`}>
                <MarkdownText content={point} className="[&_p]:m-0" />
              </li>
            ))}
          </ul>
        </div>
      </div>
    );
  }

  if (slide.layout_hint === "timeline") {
    return (
      <div className="space-y-3">
        {points.slice(0, 5).map((point, index) => (
          <div key={`${point}-${index}`} className="flex items-start gap-3">
            <div className="relative">
              <div
                className="w-8 h-8 rounded-full text-xs font-bold grid place-items-center border"
                style={{
                  background: preset.chipBg,
                  borderColor: preset.chipBorder,
                  color: accent,
                }}
              >
                {index + 1}
              </div>
              {index < points.slice(0, 5).length - 1 && (
                <div
                  className="absolute left-1/2 -translate-x-1/2 top-8 h-8 w-px"
                  style={{ background: withAlpha(muted, 0.4) }}
                />
              )}
            </div>
            <div
              className="flex-1 rounded-xl border px-3 py-2"
              style={{ background: preset.surface, borderColor: preset.border, color: foreground }}
            >
              <MarkdownText content={point} className="text-[0.95rem] leading-relaxed [&_p]:m-0" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (slide.layout_hint === "equation") {
    const [first, ...rest] = points;
    return (
      <div className="space-y-4">
        <div
          className="rounded-2xl border p-4 shadow-sm"
          style={{ background: preset.surface, borderColor: preset.border, color: foreground }}
        >
          <MarkdownText content={first || slide.objective} className="text-[1.05rem] [&_p]:m-0" />
        </div>
        <div className="flex flex-wrap gap-2">
          {rest.map((point, index) => (
            <div
              key={`${point}-${index}`}
              className="rounded-full border px-3 py-1 text-[0.86rem]"
              style={{ background: preset.chipBg, borderColor: preset.chipBorder, color: foreground }}
            >
              <MarkdownText content={point} className="[&_p]:m-0" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (slide.layout_hint === "summary") {
    return (
      <div className="space-y-4">
        <div className="space-y-2">
          {points.slice(0, 5).map((point, index) => (
            <div
              key={`${point}-${index}`}
              className="rounded-xl border px-3 py-2 text-[0.94rem] flex items-start gap-2"
              style={{ background: preset.surface, borderColor: preset.border }}
            >
              <span
                className="inline-flex mt-0.5 w-5 h-5 items-center justify-center rounded-full text-xs font-bold"
                style={{ background: preset.chipBg, color: accent }}
              >
                ✓
              </span>
              <MarkdownText content={point} className="[&_p]:m-0 leading-relaxed flex-1" />
            </div>
          ))}
        </div>
        <div
          className="rounded-xl border border-dashed px-3 py-2 text-[0.94rem]"
          style={{ background: preset.surfaceSoft, borderColor: withAlpha(muted, 0.45) }}
        >
          <MarkdownText content={slide.objective} className="[&_p]:m-0 leading-relaxed" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <MarkdownText content={slide.objective} className="text-[1rem] [&_p]:m-0 leading-relaxed" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {points.slice(0, 4).map((point, index) => (
          <div
            key={`${point}-${index}`}
            className="rounded-xl border px-3 py-2 text-[0.9rem]"
            style={{ background: preset.surface, borderColor: preset.border, color: foreground }}
          >
            <div className="text-[10px] uppercase tracking-[0.18em] mb-1" style={{ color: withAlpha(accent, 0.92) }}>
              Point {index + 1}
            </div>
            <MarkdownText content={point} className="[&_p]:m-0 leading-relaxed" />
          </div>
        ))}
      </div>
      <div className="text-[0.84rem]" style={{ color: withAlpha(muted, 0.95) }}>
        <MarkdownText content={slide.speaker_notes} className="[&_p]:m-0 leading-relaxed" />
      </div>
    </div>
  );
}

export default function SlideDeckPreview({ deck, onSlidesReady }: SlideDeckPreviewProps) {
  const theme = useMemo(() => normalizeDeckTheme(deck?.deck_theme), [deck]);
  const preset = useMemo(() => getVisualPreset(theme), [theme]);
  const slideRefs = useRef<Array<HTMLDivElement | null>>([]);

  const ratioCss = useMemo(() => ratioToCss(theme.ratio), [theme.ratio]);

  useEffect(() => {
    if (!onSlidesReady) return;
    const slides = slideRefs.current.filter(
      (node): node is HTMLDivElement => Boolean(node),
    );
    onSlidesReady(slides);
  }, [deck, onSlidesReady]);

  return (
    <div className="space-y-4">
      {deck.slides.map((slide, index) => (
        <div
          key={`${slide.title}-${index}`}
          ref={(node) => {
            slideRefs.current[index] = node;
          }}
          data-slide-export-node="true"
          className="rounded-[1.7rem] border shadow-xl overflow-hidden"
          style={{
            backgroundColor: theme.palette.background,
            color: theme.palette.foreground,
            borderColor: withAlpha(theme.palette.muted, 0.3),
            boxShadow: `0 24px 64px ${withAlpha(theme.palette.foreground, 0.2)}`,
          }}
        >
          <div
            className="relative w-full p-6 md:p-8 flex flex-col overflow-hidden"
            style={{
              aspectRatio: ratioCss,
              fontFamily: preset.bodyFont,
              backgroundImage: `${preset.texture}, ${preset.backdrop}`,
            }}
          >
            <div
              className="absolute -right-16 -top-20 w-64 h-64 rounded-full blur-2xl"
              style={{ background: withAlpha(theme.palette.accent, 0.18) }}
            />
            <div
              className="absolute -left-24 bottom-[-110px] w-72 h-72 rounded-full blur-3xl"
              style={{ background: withAlpha(theme.palette.muted, 0.18) }}
            />

            <h3
              className="font-semibold leading-[1.05] mb-4"
              style={{
                color: theme.palette.foreground,
                fontSize: `clamp(1.35rem, 2.15vw, ${theme.typography.title_scale})`,
                fontFamily: preset.titleFont,
                letterSpacing: "-0.01em",
              }}
            >
              {slide.title}
            </h3>

            <div className="relative flex-1 min-h-0 overflow-auto grid grid-cols-1 xl:grid-cols-8 gap-4">
              <div
                className="xl:col-span-5 min-h-0 overflow-auto rounded-2xl border p-4"
                style={{ background: preset.surface, borderColor: preset.border }}
              >
                <SlideBody slide={slide} theme={theme} preset={preset} />
              </div>
              <div className="xl:col-span-3 min-h-0">
                <SlideIllustration slide={slide} theme={theme} preset={preset} />
              </div>
            </div>

            {(slide.activity || slide.visual_hint) && (
              <div
                className="pt-3 mt-3 border-t text-[0.8rem] flex flex-wrap gap-2"
                style={{ borderColor: withAlpha(theme.palette.muted, 0.42) }}
              >
                {slide.activity && (
                  <div
                    className="rounded-full border px-3 py-1.5 max-w-full"
                    style={{ background: preset.surfaceSoft, borderColor: preset.border }}
                  >
                    <MarkdownText content={slide.activity} className="[&_p]:m-0 leading-relaxed" />
                  </div>
                )}
                {slide.visual_hint && (
                  <div
                    className="rounded-full border px-3 py-1.5 max-w-full truncate"
                    style={{ background: preset.surfaceSoft, borderColor: preset.border }}
                    title={slide.visual_hint}
                  >
                    {slide.visual_hint}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
