"use client";
import { apiFetch } from '@/lib/api';

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  ExternalLink,
  Loader2,
  RefreshCw,
} from "lucide-react";

type WrapperState = "loading" | "ready" | "error";

const QUIZ_GEN_PLUS_ENTRYPOINT = "/research/_quiz_gen_plus/index.html";
const QUIZ_GEN_PLUS_SOURCE_URL =
  "https://banacumbe27.github.io/pdf_quiz_generator/";

async function probeQuizGenPlus(): Promise<void> {
  const response = await apiFetch(QUIZ_GEN_PLUS_ENTRYPOINT, {
    method: "GET",
    cache: "no-store",
    credentials: "same-origin",
  });

  if (!response.ok) {
    throw new Error(
      `Quiz Gen Plus upstream returned ${response.status} ${response.statusText}`,
    );
  }
}

export function QuizGenPlusPanel() {
  const [state, setState] = useState<WrapperState>("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [frameKey, setFrameKey] = useState(0);

  const checkUpstream = useCallback(async () => {
    setState("loading");
    setErrorMessage("");

    try {
      await probeQuizGenPlus();
      setState("ready");
      setFrameKey((value) => value + 1);
    } catch (error) {
      setState("error");
      setErrorMessage(
        error instanceof Error
          ? error.message
          : "Unable to connect to Quiz Gen Plus",
      );
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void checkUpstream(); }, 0);
    return () => window.clearTimeout(timer);
  }, [checkUpstream]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-slate-50 dark:bg-slate-900">
      <div className="flex items-center justify-between border-b border-slate-200 bg-white/85 px-5 py-3 text-sm text-slate-600 backdrop-blur-sm dark:border-slate-700 dark:bg-slate-800/85 dark:text-slate-300">
        <p>
          Embedded quiz workspace running inside Research Mode via internal
          proxy.
        </p>
        <div className="flex items-center gap-2">
          <a
            href={QUIZ_GEN_PLUS_SOURCE_URL}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Open source site
          </a>
          <button
            type="button"
            onClick={() => void checkUpstream()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Reload
          </button>
        </div>
      </div>

      <div className="relative flex-1 bg-slate-100 dark:bg-slate-950">
        {state === "loading" ? (
          <div className="flex h-full w-full flex-col items-center justify-center gap-3 text-slate-600 dark:text-slate-300">
            <Loader2 className="h-6 w-6 animate-spin" />
            <p className="text-sm font-medium">Checking Quiz Gen Plus…</p>
          </div>
        ) : null}

        {state === "error" ? (
          <div className="flex h-full w-full items-center justify-center px-6 py-10">
            <div className="max-w-lg rounded-2xl border border-amber-300 bg-amber-50 p-6 text-center text-amber-950 shadow-sm dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-100">
              <div className="mx-auto mb-3 inline-flex h-10 w-10 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900/60">
                <AlertTriangle className="h-5 w-5" />
              </div>
              <h2 className="text-base font-semibold">
                Quiz Gen Plus is temporarily unavailable
              </h2>
              <p className="mt-2 text-sm">
                Edunote could not reach the embedded quiz workspace through
                `/research/_quiz_gen_plus/*`.
              </p>
              {errorMessage ? (
                <p className="mt-2 text-xs opacity-80">{errorMessage}</p>
              ) : null}
              <button
                type="button"
                onClick={() => void checkUpstream()}
                className="mt-4 inline-flex items-center gap-2 rounded-lg border border-amber-400 bg-white px-3 py-2 text-sm font-medium text-amber-900 transition hover:bg-amber-100 dark:border-amber-600 dark:bg-amber-50 dark:text-amber-950"
              >
                <RefreshCw className="h-4 w-4" />
                Retry connection
              </button>
            </div>
          </div>
        ) : null}

        {state === "ready" ? (
          <iframe
            key={frameKey}
            title="Quiz Gen Plus"
            src={QUIZ_GEN_PLUS_ENTRYPOINT}
            className="h-full w-full border-0"
            loading="eager"
            referrerPolicy="same-origin"
          />
        ) : null}
      </div>
    </div>
  );
}
