import Link from "next/link";
import { ArrowLeft, ExternalLink, ShieldCheck, Sparkles } from "lucide-react";

type GeneralBenchmarkRow = {
  benchmark: string;
  domain: string;
  base: number;
  tuned: number;
};

type SafetyStageRow = {
  stage: string;
  method: string;
  taiDucSafety: number;
  note: string;
};

const GENERAL_BENCHMARKS: GeneralBenchmarkRow[] = [
  { benchmark: "HumanEval", domain: "Python Coding", base: 62.8, tuned: 65.85 },
  { benchmark: "MBPP", domain: "Beginner Coding", base: 61.6, tuned: 62.8 },
  { benchmark: "GSM8K", domain: "Math Reasoning", base: 86.2, tuned: 85.29 },
  { benchmark: "MMLU", domain: "General Knowledge", base: 69.83, tuned: 69.7 },
  { benchmark: "HellaSwag", domain: "Commonsense Reasoning", base: 73.36, tuned: 74.35 },
  { benchmark: "ARC-Challenge", domain: "Science Reasoning", base: 54.78, tuned: 54.18 },
  { benchmark: "TruthfulQA (MC1)", domain: "Factual Truthfulness", base: 35.37, tuned: 35.86 },
];

const SAFETY_STAGES: SafetyStageRow[] = [
  {
    stage: "Base Qwen3-8B",
    method: "Reference checkpoint",
    taiDucSafety: 78.5,
    note: "Baseline before Vietnamese-domain alignment",
  },
  {
    stage: "SFT v1",
    method: "Instruction tuning",
    taiDucSafety: 84.2,
    note: "First quality jump on education + safety prompts",
  },
  {
    stage: "SFT v2",
    method: "Instruction tuning (expanded)",
    taiDucSafety: 84.8,
    note: "Improved formatting and requirement following",
  },
  {
    stage: "Merged v1",
    method: "Merge of SFT variants",
    taiDucSafety: 85.2,
    note: "Consolidated strengths from multiple adapters",
  },
  {
    stage: "DPO v1",
    method: "Preference optimization",
    taiDucSafety: 86.1,
    note: "Better safety preference ranking",
  },
  {
    stage: "DPO v2",
    method: "Preference optimization (refined)",
    taiDucSafety: 86.5,
    note: "Higher consistency on borderline cases",
  },
  {
    stage: "DPO v3",
    method: "Final preference optimization",
    taiDucSafety: 87.3,
    note: "Current best in the model card progression",
  },
];

function scoreClass(delta: number): string {
  if (delta > 0) return "text-emerald-600 dark:text-emerald-400";
  if (delta < 0) return "text-rose-600 dark:text-rose-400";
  return "text-slate-500 dark:text-slate-400";
}

export default function QwenTeacherShowcasePage() {
  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-900 px-4 py-6 md:px-8 md:py-8">
      <div className="max-w-6xl mx-auto space-y-5">
        <div className="flex items-center justify-between gap-3">
          <Link
            href="/edu_studio"
            className="inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Edu Studio
          </Link>
          <a
            href="https://huggingface.co/Hirobi07/qwen3-merged-dpo-v3-full"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border border-emerald-200 dark:border-emerald-700 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-100 dark:hover:bg-emerald-900/50"
          >
            Model Card
            <ExternalLink className="w-4 h-4" />
          </a>
        </div>

        <section className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-5 md:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl md:text-3xl font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
                <Sparkles className="w-6 h-6 text-emerald-600 dark:text-emerald-400" />
                Qwen-Teacher Model Showcase
              </h1>
              <p className="mt-2 text-sm md:text-base text-slate-600 dark:text-slate-300">
                Vietnamese education-focused 8B model:{" "}
                <span className="font-semibold">Hirobi07/qwen3-merged-dpo-v3-full</span>
              </p>
            </div>
            <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 px-3 py-2 text-xs text-slate-600 dark:text-slate-300">
              <div>Provider: huggingface</div>
              <div>Model size: 8B</div>
              <div>Recommended runtime: CUDA (`cuda:1`)</div>
            </div>
          </div>

          <div className="mt-4 grid md:grid-cols-2 gap-3 text-sm">
            <div className="rounded-xl border border-slate-200 dark:border-slate-700 p-3 bg-slate-50/70 dark:bg-slate-900/40">
              <div className="font-semibold text-slate-900 dark:text-slate-100">Authors</div>
              <div className="mt-1 text-slate-600 dark:text-slate-300">
                TRẦN HỮU VŨ PHƯƠNG - Research Assistant - VGU AI Lab <br />
                PHAN MINH HOÀI - University of Science, VNU-HCM <br />
                NGUYỄN KHÁNH TÀI - University of Information Technology, VNU-HCM
              </div>
            </div>
            <div className="rounded-xl border border-slate-200 dark:border-slate-700 p-3 bg-slate-50/70 dark:bg-slate-900/40">
              <div className="font-semibold text-slate-900 dark:text-slate-100">Training Stack</div>
              <div className="mt-1 text-slate-600 dark:text-slate-300">
                SFT (v1, v2) → Merge → DPO (v1, v2, v3) with iterative safety refinement.
              </div>
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-5 md:p-6">
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100 mb-3">
            Benchmark vs Qwen3-8B Base
          </h2>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="text-left text-slate-600 dark:text-slate-300">
                <tr className="border-b border-slate-200 dark:border-slate-700">
                  <th className="py-2 pr-4">Benchmark</th>
                  <th className="py-2 pr-4">Domain</th>
                  <th className="py-2 pr-4">Qwen3-8B Base</th>
                  <th className="py-2 pr-4">Qwen-Teacher (DPO v3)</th>
                  <th className="py-2">Delta</th>
                </tr>
              </thead>
              <tbody>
                {GENERAL_BENCHMARKS.map((row) => {
                  const delta = Number((row.tuned - row.base).toFixed(2));
                  return (
                    <tr
                      key={row.benchmark}
                      className="border-b border-slate-100 dark:border-slate-800 text-slate-700 dark:text-slate-200"
                    >
                      <td className="py-2 pr-4 font-medium">{row.benchmark}</td>
                      <td className="py-2 pr-4">{row.domain}</td>
                      <td className="py-2 pr-4">{row.base.toFixed(2)}%</td>
                      <td className="py-2 pr-4 font-semibold">{row.tuned.toFixed(2)}%</td>
                      <td className={`py-2 font-semibold ${scoreClass(delta)}`}>
                        {delta > 0 ? "+" : ""}
                        {delta.toFixed(2)}%
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            Source: Benchmark by &quot;AI Thực Chiến&quot;.
          </p>
        </section>

        <section className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-5 md:p-6">
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2 mb-3">
            <ShieldCheck className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
            SAFETY SCORE (12-Criteria Competition Rubric)
          </h2>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="text-left text-slate-600 dark:text-slate-300">
                <tr className="border-b border-slate-200 dark:border-slate-700">
                  <th className="py-2 pr-4">Stage</th>
                  <th className="py-2 pr-4">Method</th>
                  <th className="py-2 pr-4">Safety Score</th>
                  <th className="py-2">Note</th>
                </tr>
              </thead>
              <tbody>
                {SAFETY_STAGES.map((row) => (
                  <tr
                    key={row.stage}
                    className="border-b border-slate-100 dark:border-slate-800 text-slate-700 dark:text-slate-200"
                  >
                    <td className="py-2 pr-4 font-medium">{row.stage}</td>
                    <td className="py-2 pr-4">{row.method}</td>
                    <td className="py-2 pr-4 font-semibold">{row.taiDucSafety.toFixed(1)}%</td>
                    <td className="py-2">{row.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            Source: model card README benchmark progression (Tài Đức Safety Overall).
          </p>
        </section>

        <section className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-5 md:p-6">
          <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100 mb-2">
            Technical Notes
          </h2>
          <ul className="list-disc pl-5 text-sm text-slate-600 dark:text-slate-300 space-y-1">
            <li>This model is optimized for education-domain workflows and Vietnamese usage.</li>
            <li>At 8B size, prioritize cost-efficiency and customization over raw frontier performance.</li>
            <li>Use Gemini/large APIs as fallback for tasks needing stronger long-context reasoning.</li>
          </ul>
        </section>
      </div>
    </div>
  );
}
