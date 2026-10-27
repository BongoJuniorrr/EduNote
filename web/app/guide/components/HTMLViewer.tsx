"use client";

import { useMemo } from "react";
import { Bug, Loader2 } from "lucide-react";
import { useKaTeXInjection } from "../hooks";
import { useTranslation } from "react-i18next";

interface HTMLViewerProps {
  html: string;
  currentIndex: number;
  loadingMessage: string;
  onOpenDebugModal: () => void;
}

export default function HTMLViewer({
  html,
  currentIndex,
  loadingMessage,
  onOpenDebugModal,
}: HTMLViewerProps) {
  const { t } = useTranslation();
  const { injectKaTeX } = useKaTeXInjection();
  const document = useMemo(() => injectKaTeX(html), [html, injectKaTeX]);

  if (!html) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center">
        <Loader2 className="w-12 h-12 text-indigo-400 dark:text-indigo-500 animate-spin mb-4" />
        <p className="text-slate-500 dark:text-slate-400">
          {loadingMessage || t("Loading learning content...")}
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 bg-white dark:bg-slate-800 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-700 flex flex-col overflow-hidden relative">
      {/* Debug Button */}
      <button
        onClick={onOpenDebugModal}
        className="absolute top-4 right-4 z-10 p-2 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 rounded-lg transition-colors shadow-sm"
        title={t("Fix HTML")}
      >
        <Bug className="w-4 h-4 text-slate-600 dark:text-slate-300" />
      </button>

      {/* HTML Content */}
      <iframe
        srcDoc={document}
        className="w-full h-full border-0"
        title={t("Interactive Learning Content")}
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        key={`html-${currentIndex}-${html.length}`}
      />
    </div>
  );
}
