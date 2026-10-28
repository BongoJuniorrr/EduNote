"use client";
import { apiFetch } from '@/lib/api';

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Loader2, RefreshCw } from "lucide-react";

type WrapperState = "loading" | "ready" | "error";

const SLIDE_GENERATOR_ENTRYPOINT = "/slide_pro/_presenton/dashboard";
const SLIDE_GENERATOR_HEALTH_ENDPOINTS = [SLIDE_GENERATOR_ENTRYPOINT];

async function probeSlideGenerator(): Promise<void> {
  let lastError = "";

  for (const endpoint of SLIDE_GENERATOR_HEALTH_ENDPOINTS) {
    try {
      const response = await apiFetch(endpoint, {
        method: "GET",
        cache: "no-store",
        credentials: "same-origin",
      });

      if (response.ok) {
        return;
      }
      lastError = `${endpoint} returned ${response.status}`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : "Unknown upstream error";
    }
  }

  throw new Error(lastError || "Slide Generator upstream is unavailable");
}

export default function SlideProPage() {
  const [state, setState] = useState<WrapperState>("loading");
  const [errorMessage, setErrorMessage] = useState<string>("");
  const [frameKey, setFrameKey] = useState(0);

  const checkUpstream = useCallback(async () => {
    setState("loading");
    setErrorMessage("");

    try {
      await probeSlideGenerator();
      setState("ready");
      setFrameKey((value) => value + 1);
    } catch (error) {
      setState("error");
      setErrorMessage(error instanceof Error ? error.message : "Unable to connect to Slide Generator service");
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => { void checkUpstream(); }, 0);
    return () => window.clearTimeout(timer);
  }, [checkUpstream]);

  return (
    <main className="h-full w-full p-4 sm:p-6">
      <section className="mx-auto flex h-full w-full max-w-[1680px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-4 sm:px-6">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-slate-900">Slide Generator</h1>
          </div>
          <button
            type="button"
            onClick={() => void checkUpstream()}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            <RefreshCw className="h-4 w-4" />
            Retry
          </button>
        </header>

        <div className="relative flex-1 bg-slate-50">
          {state === "loading" ? (
            <div className="flex h-full w-full flex-col items-center justify-center gap-3 text-slate-600">
              <Loader2 className="h-6 w-6 animate-spin" />
              <p className="text-sm font-medium">Checking Slide Generator service...</p>
            </div>
          ) : null}

          {state === "error" ? (
            <div className="flex h-full w-full flex-col items-center justify-center px-6 text-center">
              <div className="max-w-lg rounded-xl border border-amber-300 bg-amber-50 p-6 text-amber-900">
                <div className="mb-2 inline-flex h-9 w-9 items-center justify-center rounded-full bg-amber-100">
                  <AlertTriangle className="h-5 w-5" />
                </div>
                <h2 className="text-base font-semibold">Slide Generator service is temporarily unavailable</h2>
                <p className="mt-2 text-sm">
                  Unable to reach Slide Generator upstream via `/slide_pro/_presenton/*`.
                </p>
                {errorMessage ? <p className="mt-2 text-xs opacity-80">{errorMessage}</p> : null}
                <button
                  type="button"
                  onClick={() => void checkUpstream()}
                  className="mt-4 inline-flex items-center gap-2 rounded-lg border border-amber-400 bg-white px-3 py-2 text-sm font-medium text-amber-900 transition hover:bg-amber-100"
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
              title="EduNote Slides"
              src={SLIDE_GENERATOR_ENTRYPOINT}
              className="h-full w-full border-0"
              loading="eager"
              referrerPolicy="same-origin"
            />
          ) : null}
        </div>
      </section>
    </main>
  );
}
