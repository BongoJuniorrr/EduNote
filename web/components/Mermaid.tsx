"use client";

import React, { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";
import { useTranslation } from "react-i18next";

interface MermaidProps {
  chart: string;
  className?: string;
}

function withWhiteSvgBackground(svg: string): string {
  if (!svg) {
    return svg;
  }

  if (svg.includes('style="') && svg.includes("<svg")) {
    return svg.replace(
      /<svg([^>]*)style="([^"]*)"/,
      '<svg$1style="$2;background:#ffffff;max-width:100%;height:auto"',
    );
  }

  return svg.replace(
    "<svg",
    '<svg style="background:#ffffff;max-width:100%;height:auto"',
  );
}

// Initialize mermaid with custom config
mermaid.initialize({
  startOnLoad: false,
  theme: "base",
  securityLevel: "loose",
  fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
  flowchart: {
    useMaxWidth: true,
    htmlLabels: true,
    curve: "cardinal",
  },
  themeVariables: {
    background: "#ffffff",
    mainBkg: "#ffffff",
    primaryColor: "#dbeafe",
    primaryTextColor: "#000000",
    primaryBorderColor: "#2563eb",
    secondaryColor: "#ede9fe",
    secondaryTextColor: "#000000",
    secondaryBorderColor: "#7c3aed",
    tertiaryColor: "#fef3c7",
    tertiaryTextColor: "#000000",
    tertiaryBorderColor: "#d97706",
    lineColor: "#475569",
    textColor: "#000000",
    noteTextColor: "#000000",
    noteBorderColor: "#94a3b8",
    noteBkgColor: "#f8fafc",
    clusterBkg: "#ffffff",
    clusterBorder: "#cbd5e1",
    actorBkg: "#e0f2fe",
    actorBorder: "#0284c7",
    actorTextColor: "#000000",
    actorLineColor: "#475569",
    signalColor: "#0f172a",
    labelBoxBkgColor: "#ffffff",
    labelBoxBorderColor: "#94a3b8",
    labelTextColor: "#000000",
    loopTextColor: "#000000",
    sectionBkgColor: "#f8fafc",
    sectionBkgColor2: "#fef3c7",
    sectionBorderColor: "#cbd5e1",
    taskBkgColor: "#f8fafc",
    taskTextColor: "#000000",
    taskTextDarkColor: "#000000",
  },
});

let mermaidIdCounter = 0;

export const Mermaid: React.FC<MermaidProps> = ({ chart, className = "" }) => {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [id] = useState(() => `mermaid-${++mermaidIdCounter}`);

  useEffect(() => {
    const renderChart = async () => {
      if (!chart || !containerRef.current) return;

      try {
        // Clean up the chart code
        const cleanedChart = chart.trim();

        // Validate and render
        const { svg: renderedSvg } = await mermaid.render(id, cleanedChart);
        setSvg(withWhiteSvgBackground(renderedSvg));
        setError(null);
      } catch (err) {
        console.error("Mermaid rendering error:", err);
        setError(
          err instanceof Error ? err.message : "Failed to render diagram",
        );
      }
    };

    renderChart();
  }, [chart, id]);

  if (error) {
    return (
      <div
        className={`my-4 p-4 bg-red-50 border border-red-200 rounded-lg ${className}`}
      >
        <p className="text-red-600 text-sm font-medium mb-2">
          {t("Diagram rendering error")}
        </p>
        <pre className="text-xs text-red-500 whitespace-pre-wrap">{error}</pre>
        <details className="mt-2">
          <summary className="text-xs text-slate-500 cursor-pointer">
            {t("Show source")}
          </summary>
          <pre className="mt-2 p-2 bg-slate-100 rounded text-xs overflow-x-auto">
            {chart}
          </pre>
        </details>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={`my-6 flex justify-center overflow-x-auto ${className}`}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
};

export default Mermaid;
