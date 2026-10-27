"use client";
import { apiFetch } from '@/lib/api';

import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  ClipboardList,
  Database,
  Loader2,
  Play,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Workflow,
} from "lucide-react";

import { apiUrl, wsUrl } from "@/lib/api";
import {
  MissionArtifact,
  MissionEvent,
  MissionRun,
  MissionRunSummary,
  MissionTemplate,
} from "@/types/mission";

interface NotebookSummary {
  id: string;
  name: string;
  description: string;
  record_count: number;
}

interface KnowledgeBase {
  name: string;
  is_default?: boolean;
}

const OUTPUT_OPTIONS = [
  "knowledge_map",
  "idea_board",
  "research_brief",
  "study_plan",
  "scope_options",
  "risk_register",
  "execution_roadmap",
  "weakness_audit",
  "qa_bank",
  "defense_strategy",
  "next_actions",
];

function statusClass(status: MissionRun["status"]) {
  switch (status) {
    case "completed":
      return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300";
    case "running":
      return "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300";
    case "approved":
      return "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300";
    case "awaiting_approval":
      return "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300";
    case "failed":
      return "bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300";
    default:
      return "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300";
  }
}

function stepClass(status: MissionRun["plan"][number]["status"]) {
  switch (status) {
    case "completed":
      return "border-emerald-200 bg-emerald-50/80 dark:border-emerald-800 dark:bg-emerald-950/40";
    case "running":
      return "border-blue-200 bg-blue-50/80 dark:border-blue-800 dark:bg-blue-950/40";
    case "failed":
      return "border-rose-200 bg-rose-50/80 dark:border-rose-800 dark:bg-rose-950/40";
    default:
      return "border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800/80";
  }
}

function mergeRunStep(
  run: MissionRun,
  stepId: string,
  patch: Partial<MissionRun["plan"][number]>,
) {
  return {
    ...run,
    plan: run.plan.map((step) =>
      step.step_id === stepId ? { ...step, ...patch } : step,
    ),
  };
}

function addArtifact(run: MissionRun, artifact: MissionArtifact): MissionRun {
  const withoutDup = run.artifacts.filter(
    (item) => item.artifact_id !== artifact.artifact_id,
  );
  return { ...run, artifacts: [...withoutDup, artifact] };
}

export default function MissionPage() {
  const wsRef = useRef<WebSocket | null>(null);

  const [templates, setTemplates] = useState<MissionTemplate[]>([]);
  const [runs, setRuns] = useState<MissionRunSummary[]>([]);
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);

  const [goal, setGoal] = useState("");
  const [preset, setPreset] = useState<MissionTemplate["id"]>("learn_topic");
  const [constraints, setConstraints] = useState("");
  const [successCriteria, setSuccessCriteria] = useState("");
  const [researchDepth, setResearchDepth] = useState<"quick" | "medium" | "deep">("medium");
  const [primaryKbName, setPrimaryKbName] = useState("");
  const [selectedNotebookIds, setSelectedNotebookIds] = useState<string[]>([]);
  const [desiredOutputs, setDesiredOutputs] = useState<string[]>([]);

  const [activeRun, setActiveRun] = useState<MissionRun | null>(null);
  const [events, setEvents] = useState<MissionEvent[]>([]);
  const [artifactBody, setArtifactBody] = useState("");
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(
    null,
  );

  const [isPlanning, setIsPlanning] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [loadingRunId, setLoadingRunId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState("");

  const [previousTemplate, setPreviousTemplate] = useState<MissionTemplate | undefined>();
  const currentTemplate = templates.find(item => item.id === preset);
  if (previousTemplate !== currentTemplate) {
    setPreviousTemplate(currentTemplate); setDesiredOutputs(currentTemplate?.default_outputs || []);
  }

  const selectedArtifact = useMemo(
    () =>
      activeRun?.artifacts.find(
        (artifact) => artifact.artifact_id === selectedArtifactId,
      ) || [...(activeRun?.artifacts || [])].reverse().find(item => item.kind === "final_dossier") || [...(activeRun?.artifacts || [])].reverse()[0] || null,
    [activeRun, selectedArtifactId],
  );

  const loadTemplates = async () => {
    const res = await apiFetch(apiUrl("/api/v1/mission/templates"));
    const data = await res.json();
    setTemplates(data.presets || []);
  };

  const loadRuns = async () => {
    const res = await apiFetch(apiUrl("/api/v1/mission/runs"));
    const data = await res.json();
    setRuns(data.runs || []);
  };

  const loadNotebooks = async () => {
    const res = await apiFetch(apiUrl("/api/v1/notebook/list"));
    const data = await res.json();
    setNotebooks(data.notebooks || []);
  };

  const loadKnowledgeBases = async () => {
    const res = await apiFetch(apiUrl("/api/v1/knowledge/list"));
    const data = await res.json();
    const list = Array.isArray(data) ? data : [];
    setKbs(list);
    if (!primaryKbName && list.length > 0) {
      const defaultKb = list.find((kb: KnowledgeBase) => kb.is_default);
      setPrimaryKbName(defaultKb?.name || list[0].name);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    const load = (path: string) => apiFetch(apiUrl(path), { signal: controller.signal }).then(response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    });
    void Promise.all([
      load("/api/v1/mission/templates").then(data => setTemplates(data.presets || [])),
      load("/api/v1/mission/runs").then(data => setRuns(data.runs || [])),
      load("/api/v1/notebook/list").then(data => setNotebooks(data.notebooks || [])),
      load("/api/v1/knowledge/list").then(data => { const list = Array.isArray(data) ? data : []; setKbs(list); setPrimaryKbName(list.find((kb: KnowledgeBase) => kb.is_default)?.name || list[0]?.name || ""); }),
    ]).catch(error => { if (error.name !== "AbortError") setErrorMessage(`Could not load workspace: ${error.message}`); });

    return () => {
      controller.abort();
      if (wsRef.current) wsRef.current.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const loadArtifact = async () => {
      if (!selectedArtifact) {
        setArtifactBody("");
        return;
      }

      setArtifactLoading(true);
      try {
        const res = await apiFetch(apiUrl(selectedArtifact.url));
        const text = await res.text();
        setArtifactBody(text || selectedArtifact.preview || "");
      } catch {
        setArtifactBody(selectedArtifact.preview || "");
      } finally {
        setArtifactLoading(false);
      }
    };

    void loadArtifact();
  }, [selectedArtifact]);

  const handleOutputToggle = (output: string) => {
    setDesiredOutputs((current) =>
      current.includes(output)
        ? current.filter((item) => item !== output)
        : [...current, output],
    );
  };

  const handleNotebookToggle = (notebookId: string) => {
    setSelectedNotebookIds((current) =>
      current.includes(notebookId)
        ? current.filter((item) => item !== notebookId)
        : [...current, notebookId],
    );
  };

  const refreshRun = async (runId: string) => {
    setLoadingRunId(runId);
    try {
      const res = await apiFetch(apiUrl(`/api/v1/mission/runs/${runId}`));
      const data = await res.json();
      setActiveRun(data.run || null);
      setEvents(data.run?.events || []);
    } finally {
      setLoadingRunId(null);
    }
  };

  const handlePlan = async () => {
    if (!goal.trim()) return;
    setIsPlanning(true);
    setErrorMessage("");
    setEvents([]);
    try {
      const res = await apiFetch(apiUrl("/api/v1/mission/plan"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          goal,
          preset,
          notebook_ids: selectedNotebookIds,
          primary_kb_name: primaryKbName || null,
          desired_outputs: desiredOutputs,
          constraints,
          success_criteria: successCriteria,
          research_depth: researchDepth,
          auto_approve_plan: false,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Failed to create mission plan");
      }
      setActiveRun(data.run);
      setEvents(data.run?.events || []);
      await loadRuns();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Plan failed");
    } finally {
      setIsPlanning(false);
    }
  };

  const handleApprove = async () => {
    if (!activeRun) return;
    setErrorMessage("");
    try {
      const res = await apiFetch(
        apiUrl(`/api/v1/mission/runs/${activeRun.run_id}/approve`),
        { method: "POST" },
      );
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Failed to approve mission");
      }
      setActiveRun(data.run);
      await loadRuns();
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "Approval failed",
      );
    }
  };

  const handleMissionEvent = (event: MissionEvent) => {
    setEvents((current) => [...current.slice(-149), event]);
    setActiveRun((current) => {
      if (!current) return current;

      if (event.type === "run_started") {
        return { ...current, status: "running" };
      }
      if (event.type === "step_started") {
        return mergeRunStep(current, event.step_id, {
          status: "running",
          summary: "",
        });
      }
      if (event.type === "step_completed") {
        return mergeRunStep(current, event.step_id, {
          status: "completed",
          summary: event.summary || "",
          artifact_ids: event.artifact_ids || [],
        });
      }
      if (event.type === "step_failed") {
        return mergeRunStep(current, event.step_id, {
          status: "failed",
          summary: event.message || "Step failed",
        });
      }
      if (event.type === "artifact_created" && event.artifact) {
        return addArtifact(current, event.artifact);
      }
      if (event.type === "review_completed" && event.review) {
        return { ...current, review: event.review };
      }
      if (event.type === "run_completed") {
        return {
          ...current,
          status: "completed",
          result_summary: event.result_summary || current.result_summary,
          review: event.review || current.review,
        };
      }
      if (event.type === "error") {
        return { ...current, status: "failed", error: event.message };
      }
      return current;
    });
  };

  const handleExecute = async () => {
    if (!activeRun) return;
    if (wsRef.current) wsRef.current.close();

    setIsRunning(true);
    setErrorMessage("");
    const ws = new WebSocket(wsUrl("/api/v1/mission/run"));
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ run_id: activeRun.run_id }));
    };

    ws.onmessage = (message) => {
      const data = JSON.parse(message.data);
      if (data.type === "result") {
        setActiveRun(data.run || null);
        setEvents(data.run?.events || []);
        setIsRunning(false);
        void loadRuns();
        return;
      }
      if (data.type === "error") {
        setErrorMessage(data.message || "Mission execution failed");
        setIsRunning(false);
      }
      handleMissionEvent(data);
    };

    ws.onerror = () => {
      setErrorMessage("Mission websocket connection failed");
      setIsRunning(false);
    };

    ws.onclose = () => {
      setIsRunning(false);
    };
  };

  const runReady = activeRun?.status === "approved";

  return (
    <div className="h-screen overflow-hidden p-4 sm:p-6 animate-fade-in">
      <div className="grid h-full gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <section className="min-h-0 space-y-4 overflow-y-auto pr-1">
          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-800">
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300">
                <Workflow className="h-5 w-5" />
              </div>
              <div>
                <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                  Agentic Mission Mode
                </h1>
              </div>
            </div>

            <div className="mb-4 rounded-2xl border border-sky-200 bg-sky-50/80 p-4 dark:border-sky-800 dark:bg-sky-950/30">
              <div className="mb-2 text-sm font-semibold text-sky-900 dark:text-sky-100">
                How to use
              </div>
              <ol className="space-y-1 text-xs leading-5 text-sky-800 dark:text-sky-200">
                <li>1. Write the final outcome you want in Goal.</li>
                <li>2. Attach the main KB, notebooks, and outputs you expect.</li>
                <li>3. Click Generate Plan, review the steps, then Approve Plan.</li>
                <li>4. Click Run Mission and inspect the artifacts on the right.</li>
              </ol>
            </div>

            <label className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-200">
              Goal
            </label>
            <textarea
              value={goal}
              onChange={(e) => setGoal(e.target.value)}
              rows={5}
              className="mb-4 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
              placeholder="Example: From my AI notebook and textbook KB, create a defense prep pack with a knowledge map, likely questions, and a final review brief."
            />

            <div className="mb-4 grid gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-200">
                  Preset
                </label>
                <select
                  value={preset}
                  onChange={(e) =>
                    setPreset(e.target.value as MissionTemplate["id"])
                  }
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
                >
                  {templates.map((template) => (
                    <option key={template.id} value={template.id}>
                      {template.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-200">
                  Research Depth
                </label>
                <select
                  value={researchDepth}
                  onChange={(e) =>
                    setResearchDepth(
                      e.target.value as "quick" | "medium" | "deep",
                    )
                  }
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
                >
                  <option value="quick">Quick</option>
                  <option value="medium">Medium</option>
                  <option value="deep">Deep</option>
                </select>
              </div>
            </div>

            <div className="mb-4">
              <label className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                <Database className="h-4 w-4" />
                Primary Knowledge Base
              </label>
              <select
                value={primaryKbName}
                onChange={(e) => setPrimaryKbName(e.target.value)}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
              >
                <option value="">No KB</option>
                {kbs.map((kb) => (
                  <option key={kb.name} value={kb.name}>
                    {kb.name}
                  </option>
                ))}
              </select>
            </div>

            <div className="mb-4">
              <label className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                <BookOpen className="h-4 w-4" />
                Notebooks
              </label>
              <div className="max-h-40 space-y-2 overflow-y-auto rounded-xl border border-slate-200 p-3 dark:border-slate-700">
                {notebooks.length === 0 ? (
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    No notebooks available.
                  </p>
                ) : (
                  notebooks.map((notebook) => (
                    <label
                      key={notebook.id}
                      className="flex cursor-pointer items-start gap-3 rounded-lg px-2 py-1.5 hover:bg-slate-50 dark:hover:bg-slate-700/50"
                    >
                      <input
                        type="checkbox"
                        checked={selectedNotebookIds.includes(notebook.id)}
                        onChange={() => handleNotebookToggle(notebook.id)}
                        className="mt-1"
                      />
                      <div>
                        <div className="text-sm font-medium text-slate-800 dark:text-slate-100">
                          {notebook.name}
                        </div>
                        <div className="text-xs text-slate-500 dark:text-slate-400">
                          {notebook.record_count} records
                        </div>
                      </div>
                    </label>
                  ))
                )}
              </div>
            </div>

            <div className="mb-4">
              <label className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-200">
                Desired Outputs
              </label>
              <div className="flex flex-wrap gap-2">
                {OUTPUT_OPTIONS.map((output) => {
                  const active = desiredOutputs.includes(output);
                  return (
                    <button
                      key={output}
                      type="button"
                      onClick={() => handleOutputToggle(output)}
                      className={`rounded-full border px-3 py-1.5 text-xs transition ${
                        active
                          ? "border-sky-300 bg-sky-100 text-sky-700 dark:border-sky-700 dark:bg-sky-900/30 dark:text-sky-300"
                          : "border-slate-200 bg-white text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
                      }`}
                    >
                      {output}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="mb-4">
              <label className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-200">
                Constraints
              </label>
              <textarea
                value={constraints}
                onChange={(e) => setConstraints(e.target.value)}
                rows={3}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
                placeholder="Optional: time budget, tone, must-use materials, exclusions..."
              />
            </div>

            <div className="mb-5">
              <label className="mb-2 block text-sm font-medium text-slate-700 dark:text-slate-200">
                Success Criteria
              </label>
              <textarea
                value={successCriteria}
                onChange={(e) => setSuccessCriteria(e.target.value)}
                rows={3}
                className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-sky-400 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
                placeholder="Optional: what would make this mission good enough to trust?"
              />
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void handlePlan()}
                disabled={isPlanning || !goal.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-sky-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isPlanning ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <ClipboardList className="h-4 w-4" />
                )}
                Generate Plan
              </button>

              {activeRun?.status === "awaiting_approval" ? (
                <button
                  type="button"
                  onClick={() => void handleApprove()}
                  className="inline-flex items-center gap-2 rounded-xl border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm font-medium text-amber-800 transition hover:bg-amber-100 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
                >
                  <ShieldCheck className="h-4 w-4" />
                  Approve Plan
                </button>
              ) : null}

              <button
                type="button"
                onClick={() => void handleExecute()}
                disabled={!activeRun || !runReady || isRunning}
                className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
              >
                {isRunning ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Play className="h-4 w-4" />
                )}
                Run Mission
              </button>
            </div>

            {errorMessage ? (
              <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300">
                {errorMessage}
              </div>
            ) : null}
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-800">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                Recent Runs
              </h2>
              <button
                type="button"
                onClick={() => void loadRuns()}
                className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 dark:hover:bg-slate-700"
              >
                <RefreshCw className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-2">
              {runs.map((run) => (
                <button
                  key={run.run_id}
                  type="button"
                  onClick={() => void refreshRun(run.run_id)}
                  className="w-full rounded-xl border border-slate-200 px-3 py-3 text-left transition hover:border-sky-300 hover:bg-sky-50/50 dark:border-slate-700 dark:hover:border-sky-700 dark:hover:bg-sky-950/30"
                >
                  <div className="mb-1 flex items-center justify-between gap-3">
                    <div className="truncate text-sm font-medium text-slate-800 dark:text-slate-100">
                      {run.title}
                    </div>
                    {loadingRunId === run.run_id ? (
                      <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
                    ) : null}
                  </div>
                  <div className="mb-2 line-clamp-2 text-xs text-slate-500 dark:text-slate-400">
                    {run.goal}
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    <span
                      className={`rounded-full px-2 py-1 ${statusClass(run.status)}`}
                    >
                      {run.status}
                    </span>
                    <span className="text-slate-400">
                      {run.artifact_count} artifacts
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </section>

        <section className="min-h-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-800">
          {activeRun ? (
            <div className="flex h-full flex-col">
              <div className="border-b border-slate-200 px-5 py-4 dark:border-slate-700">
                <div className="flex flex-wrap items-center gap-3">
                  <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                    {activeRun.title}
                  </h2>
                  <span
                    className={`rounded-full px-2.5 py-1 text-xs font-medium ${statusClass(
                      activeRun.status,
                    )}`}
                  >
                    {activeRun.status}
                  </span>
                  {activeRun.review ? (
                    <span
                      className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                        activeRun.review.status === "pass"
                          ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"
                          : "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300"
                      }`}
                    >
                      review: {activeRun.review.status} ({activeRun.review.score.toFixed(2)})
                    </span>
                  ) : null}
                </div>
                <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                  {activeRun.brief?.objective || activeRun.goal}
                </p>
              </div>

              <div className="grid min-h-0 flex-1 gap-4 p-4 xl:grid-cols-[380px_minmax(0,1fr)]">
                <div className="min-h-0 space-y-4 overflow-y-auto pr-1">
                  <div className="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
                    <div className="mb-3 flex items-center gap-2">
                      <ClipboardList className="h-4 w-4 text-sky-600 dark:text-sky-300" />
                      <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        Plan
                      </h3>
                    </div>
                    <div className="space-y-3">
                      {activeRun.plan.map((step) => (
                        <div
                          key={step.step_id}
                          className={`rounded-xl border p-3 ${stepClass(step.status)}`}
                        >
                          <div className="mb-1 flex items-center justify-between gap-3">
                            <div className="text-sm font-medium text-slate-900 dark:text-slate-100">
                              {step.title}
                            </div>
                            <span className="text-xs uppercase tracking-wide text-slate-400">
                              {step.status}
                            </span>
                          </div>
                          <div className="text-xs text-slate-500 dark:text-slate-400">
                            {step.rationale || step.step_type}
                          </div>
                          {step.summary ? (
                            <div className="mt-2 text-xs text-slate-600 dark:text-slate-300">
                              {step.summary}
                            </div>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
                    <div className="mb-3 flex items-center gap-2">
                      <Sparkles className="h-4 w-4 text-fuchsia-600 dark:text-fuchsia-300" />
                      <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        Live Events
                      </h3>
                    </div>
                    <div className="max-h-[360px] space-y-2 overflow-y-auto">
                      {events.length === 0 ? (
                        <div className="text-sm text-slate-500 dark:text-slate-400">
                          No events yet.
                        </div>
                      ) : (
                        [...events].reverse().map((event, index) => (
                          <div
                            key={`${event.timestamp || "evt"}-${index}`}
                            className="rounded-xl border border-slate-200 px-3 py-2 dark:border-slate-700"
                          >
                            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">
                              {event.type}
                            </div>
                            <pre className="overflow-x-auto whitespace-pre-wrap text-xs text-slate-700 dark:text-slate-300">
                              {JSON.stringify(event, null, 2)}
                            </pre>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </div>

                <div className="grid min-h-0 gap-4 xl:grid-rows-[auto_minmax(0,1fr)]">
                  <div className="rounded-2xl border border-slate-200 p-4 dark:border-slate-700">
                    <div className="mb-3 flex items-center gap-2">
                      <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-300" />
                      <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                        Artifacts
                      </h3>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {activeRun.artifacts.map((artifact) => (
                        <button
                          key={artifact.artifact_id}
                          type="button"
                          onClick={() => setSelectedArtifactId(artifact.artifact_id)}
                          className={`rounded-xl border px-3 py-2 text-left text-xs transition ${
                            selectedArtifactId === artifact.artifact_id
                              ? "border-sky-400 bg-sky-50 dark:border-sky-700 dark:bg-sky-950/40"
                              : "border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900"
                          }`}
                        >
                          <div className="font-medium text-slate-800 dark:text-slate-100">
                            {artifact.title}
                          </div>
                          <div className="mt-1 text-slate-500 dark:text-slate-400">
                            {artifact.kind}
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="min-h-0 overflow-hidden rounded-2xl border border-slate-200 dark:border-slate-700">
                    <div className="border-b border-slate-200 px-4 py-3 dark:border-slate-700">
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                            {selectedArtifact?.title || "Artifact Preview"}
                          </h3>
                          <p className="text-xs text-slate-500 dark:text-slate-400">
                            {selectedArtifact?.summary || activeRun.result_summary || "Select an artifact to inspect the output."}
                          </p>
                        </div>
                        {selectedArtifact?.url ? (
                          <a
                            href={apiUrl(selectedArtifact.url)}
                            target="_blank"
                            rel="noreferrer"
                            className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                          >
                            Open file
                          </a>
                        ) : null}
                      </div>
                    </div>

                    <div className="h-full overflow-y-auto px-4 py-4">
                      {artifactLoading ? (
                        <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Loading artifact...
                        </div>
                      ) : !selectedArtifact ? (
                        <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
                          <AlertTriangle className="h-4 w-4" />
                          No artifact selected yet.
                        </div>
                      ) : selectedArtifact.content_type.includes("markdown") ? (
                        <div className="prose prose-slate max-w-none dark:prose-invert">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {artifactBody}
                          </ReactMarkdown>
                        </div>
                      ) : (
                        <pre className="overflow-x-auto whitespace-pre-wrap rounded-xl bg-slate-50 p-4 text-xs text-slate-700 dark:bg-slate-900 dark:text-slate-200">
                          {artifactBody}
                        </pre>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex h-full flex-col items-center justify-center px-8 text-center">
              <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-3xl bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300">
                <Workflow className="h-7 w-7" />
              </div>
              <h2 className="mb-2 text-xl font-semibold text-slate-900 dark:text-slate-100">
                Agentic mission workspace is ready
              </h2>
              <p className="max-w-xl text-sm leading-6 text-slate-500 dark:text-slate-400">
                Start with one clear goal. The system will turn it into a plan,
                wait for your approval, run each step, then collect the final
                artifacts in one workspace.
              </p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
