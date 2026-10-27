"use client";

import { QuizGenPlusPanel } from "@/components/research/QuizGenPlusPanel";

export default function QuizGenPlusPage() {
  return (
    <main className="h-full w-full p-4 sm:p-6">
      <section className="mx-auto flex h-full w-full max-w-[1680px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-800">
        <header className="border-b border-slate-200 px-5 py-4 sm:px-6 dark:border-slate-700">
          <h1 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-slate-100">
            Quiz Gen Plus
          </h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            Research companion workspace for generating and playing quizzes from
            PDFs inside EduNote.
          </p>
        </header>

        <div className="min-h-0 flex-1">
          <QuizGenPlusPanel />
        </div>
      </section>
    </main>
  );
}
