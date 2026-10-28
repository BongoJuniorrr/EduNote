import { BookOpen, Github, Globe, GraduationCap } from "lucide-react";

export default function AboutPage() {
  return (
    <main className="mx-auto max-w-4xl space-y-8 px-6 py-12">
      <section className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm dark:border-slate-700 dark:bg-slate-800">
        <BookOpen className="mb-4 h-10 w-10 text-blue-500" aria-hidden="true" />
        <h1 className="text-3xl font-bold">About EduNote</h1>
        <p className="mt-4 text-lg text-slate-600 dark:text-slate-300">
          A personal AI learning workspace for your documents, questions, research,
          notes, and presentations. Built for one owner, with configurable models
          and document processing pipelines.
        </p>
      </section>
      <section className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm dark:border-slate-700 dark:bg-slate-800">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-blue-500">Author</h2>
        <p className="mt-3 text-2xl font-bold">Tran Huu Vu Phuong</p>
        <p className="mt-3 flex items-center gap-2 text-slate-600 dark:text-slate-300">
          <GraduationCap className="h-5 w-5 shrink-0" aria-hidden="true" />
          CSE 2025 - Vietnamese-German University
        </p>
        <p className="mt-4 text-slate-600 dark:text-slate-300">
          EduNote is developed and maintained by Tran Huu Vu Phuong.
          The project uses open-source libraries and external model providers;
          their respective licenses and credits remain applicable.
        </p>
      </section>
      <nav aria-label="Project links" className="flex flex-wrap gap-4">
        <a href="https://github.com/BongoJuniorrr/EduNote" target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-3 font-medium text-white hover:bg-blue-700">
          <Github className="h-5 w-5" aria-hidden="true" /> GitHub
        </a>
        <a href="https://edunote.thvphuong.id.vn" target="_blank" rel="noopener noreferrer"
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 px-5 py-3 font-medium hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-800">
          <Globe className="h-5 w-5" aria-hidden="true" /> Official demo
        </a>
      </nav>
    </main>
  );
}
