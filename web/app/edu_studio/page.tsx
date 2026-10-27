"use client";
import { apiFetch, readApiResponse } from '@/lib/api';

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Sparkles,
  Play,
  Loader2,
  Upload,
  Copy,
  Check,
  Download,
  FileText,
  Settings2,
  BookOpen,
  AlertTriangle,
  ArrowUpRight,
  ImageIcon,
  FileDown,
  Presentation,
} from "lucide-react";

import { apiUrl } from "@/lib/api";
import NotebookImportModal from "@/components/NotebookImportModal";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import SlideDeckPreview from "@/components/edu-studio/SlideDeckPreview";
import {
  blobToFile,
  buildSlidesPdf,
  buildSlidesPptx,
  buildSlidesZip,
  captureSlidesAsPng,
  downloadBlob,
} from "@/components/edu-studio/slideExport";
import {
  ArtifactMeta,
  ArtifactUploadResponse,
  ContextEnrichmentConfig,
  EduStudioRunRequest,
  EduStudioRunResponse,
  RAGMode,
  SearchMode,
  SettingsTemplate,
  SettingsValue,
  SlideDeckData,
  WorkflowCatalogResponse,
  WorkflowConfig,
  WorkflowType,
} from "@/types/eduStudio";

interface NotebookRecord {
  id: string;
  title: string;
  user_query: string;
  output: string;
  type: string;
}

interface LlmOption {
  id: string;
  name: string;
  provider: string;
  model: string;
  is_active: boolean;
  metadata?: {
    device?: string;
  };
}

interface KnowledgeBaseInfo {
  name: string;
  is_default?: boolean;
  statistics?: {
    rag_initialized?: boolean;
    status?: string;
    rag_provider?: string;
    raw_documents?: number;
    content_lists?: number;
  };
}

const EMPTY_WORKFLOW_CONFIG: WorkflowConfig = {
  id: "slide_deck",
  name: "Slide Generator",
  description: "Generate presentation-ready slide decks.",
  templates: [
    {
      id: "default",
      name: "Default",
      description: "Waiting for server templates...",
      settings: {
        slide_count: 10,
        style: "clean-academic",
        style_directives: "",
      },
    },
  ],
};

const SEARCH_PROVIDER_OPTIONS = [
  { id: "default", label: "Default Provider" },
  { id: "perplexity", label: "Perplexity" },
  { id: "tavily", label: "Tavily" },
  { id: "exa", label: "Exa" },
  { id: "serper", label: "Serper" },
  { id: "jina", label: "Jina" },
  { id: "baidu", label: "Baidu" },
];

const SLIDE_STYLE_OPTIONS = [
  { id: "clean-academic", label: "Clean Academic" },
  { id: "modern-grid", label: "Modern Grid" },
  { id: "executive-impact", label: "Executive Impact" },
  { id: "visual-storytelling", label: "Visual Storytelling" },
  { id: "data-briefing", label: "Data Briefing" },
  { id: "chalkboard", label: "Chalkboard" },
];

const SLIDE_STYLE_DIRECTIVE_PRESETS: Array<{
  id: string;
  label: string;
  style: string;
  directives: string;
}> = [
  {
    id: "executive_minimal",
    label: "Executive Minimal",
    style: "executive-impact",
    directives:
      "Minimal executive deck. Use short declarative headlines, strong whitespace, and one strategic visual per slide. Avoid playful icons and avoid dense bullet blocks.",
  },
  {
    id: "story_cinematic",
    label: "Story Cinematic",
    style: "visual-storytelling",
    directives:
      "Narrative-first deck with cinematic rhythm. Each slide should have one focal visual metaphor, emotional transition, and concise supporting points.",
  },
  {
    id: "data_consulting",
    label: "Data Consulting",
    style: "data-briefing",
    directives:
      "Consulting data style. Prioritize chart/table-like structure, evidence labels, and implications. Keep analytical language and explicit decision takeaway.",
  },
  {
    id: "teaching_interactive",
    label: "Teaching Interactive",
    style: "clean-academic",
    directives:
      "Interactive lecture style. Keep clear concept progression, include micro-activities, and use diagrams with labeled parts for recall.",
  },
];

const QWEN_TEACHER_CONFIG_ID = "qwen_teacher_env";

function uniqueArtifacts(existing: ArtifactMeta[], incoming: ArtifactMeta[]): ArtifactMeta[] {
  const seen = new Set<string>();
  const merged = [...existing, ...incoming];

  return merged.filter((artifact) => {
    const key = artifact.url || `${artifact.file_name}-${artifact.uploaded_at}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function asSlideDeckData(raw: Record<string, unknown> | undefined): SlideDeckData | null {
  if (!raw || typeof raw !== "object") return null;
  if (!Array.isArray(raw.slides)) return null;
  if (!raw.deck_theme || typeof raw.deck_theme !== "object") return null;
  return raw as unknown as SlideDeckData;
}

function cloneTemplateSettings(template?: SettingsTemplate): Record<string, SettingsValue> {
  if (!template) return {};
  return Object.fromEntries(
    Object.entries(template.settings).map(([key, value]) => [
      key,
      Array.isArray(value) ? [...value] : value,
    ]),
  ) as Record<string, SettingsValue>;
}

function getDefaultTemplate(config?: WorkflowConfig): SettingsTemplate | undefined {
  if (!config || !Array.isArray(config.templates) || config.templates.length === 0) {
    return undefined;
  }
  return config.templates[0];
}

export default function EduStudioPage() {
  const [workflow, setWorkflow] = useState<WorkflowType>("slide_deck");
  const [workflowConfigs, setWorkflowConfigs] = useState<WorkflowConfig[]>([]);
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState<"vi" | "en">("vi");
  const [sourceText, setSourceText] = useState("");
  const [instructions, setInstructions] = useState("");
  const initialWorkflow = EMPTY_WORKFLOW_CONFIG;
  const initialTemplate = getDefaultTemplate(initialWorkflow);
  const [selectedTemplateId, setSelectedTemplateId] = useState(initialTemplate?.id || "");
  const [settings, setSettings] = useState<Record<string, SettingsValue>>(
    cloneTemplateSettings(initialTemplate),
  );
  const [files, setFiles] = useState<File[]>([]);
  const [llmOptions, setLlmOptions] = useState<LlmOption[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseInfo[]>([]);
  const [modelConfigId, setModelConfigId] = useState("active");
  const [enableRag, setEnableRag] = useState(false);
  const [ragKbName, setRagKbName] = useState("");
  const [ragMode, setRagMode] = useState<RAGMode>("hybrid");
  const [enableWebSearch, setEnableWebSearch] = useState(false);
  const [searchMode, setSearchMode] = useState<SearchMode>("balanced");
  const [searchProvider, setSearchProvider] = useState("default");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [result, setResult] = useState<EduStudioRunResponse | null>(null);
  const [showNotebookImport, setShowNotebookImport] = useState(false);
  const [slideNodes, setSlideNodes] = useState<HTMLDivElement[]>([]);
  const [exporting, setExporting] = useState<"images" | "pdf" | "pptx" | null>(null);
  const [artifactNotice, setArtifactNotice] = useState("");

  const availableWorkflows = useMemo(
    () => (workflowConfigs.length > 0 ? workflowConfigs : [EMPTY_WORKFLOW_CONFIG]),
    [workflowConfigs],
  );

  const selectedWorkflow = useMemo(
    () => availableWorkflows.find((wf) => wf.id === workflow) || availableWorkflows[0],
    [availableWorkflows, workflow],
  );
  const selectedTemplate = useMemo(
    () =>
      selectedWorkflow.templates.find((template) => template.id === selectedTemplateId) ||
      getDefaultTemplate(selectedWorkflow),
    [selectedTemplateId, selectedWorkflow],
  );

  const slideDeckData = useMemo(
    () => asSlideDeckData(result?.result?.structured_data),
    [result],
  );
  const selectedKnowledgeBase = useMemo(
    () => knowledgeBases.find((kb) => kb.name === ragKbName),
    [knowledgeBases, ragKbName],
  );
  const ragUnavailable = useMemo(
    () =>
      Boolean(
        enableRag &&
          ragKbName &&
          selectedKnowledgeBase &&
          selectedKnowledgeBase.statistics?.rag_initialized === false,
      ),
    [enableRag, ragKbName, selectedKnowledgeBase],
  );

  useEffect(() => {
    const loadWorkflowTemplates = async () => {
      try {
        const res = await apiFetch(apiUrl("/api/v1/edu-studio/templates"));
        if (!res.ok) return;
        const data = (await res.json()) as WorkflowCatalogResponse;
        const workflows = Array.isArray(data.workflows) ? data.workflows : [];
        if (!workflows.length) return;

        setWorkflowConfigs(workflows);
        const initial = workflows.find(item => item.id === workflow) || workflows[0];
        const template = getDefaultTemplate(initial);
        setSelectedTemplateId(template?.id || "");
        setSettings({ style_directives: "", ...cloneTemplateSettings(template) });
        setWorkflow((prev) =>
          workflows.some((item) => item.id === prev) ? prev : workflows[0].id,
        );
      } catch (fetchError) {
        console.error("Failed to load workflow templates:", fetchError);
      }
    };

    const loadLlmOptions = async () => {
      try {
        const res = await apiFetch(apiUrl("/api/v1/edu-studio/llm-options"));
        if (!res.ok) return;
        const data = await res.json();
        const configs = Array.isArray(data.configs) ? data.configs : [];
        const seen = new Set<string>();
        const deduped = configs.filter((cfg: LlmOption) => {
          if (cfg?.id === "default" || cfg?.id === "active") return false;
          if (!cfg?.id || seen.has(cfg.id)) return false;
          seen.add(cfg.id);
          return true;
        });
        setLlmOptions(deduped);
      } catch (fetchError) {
        console.error("Failed to load LLM options:", fetchError);
      }
    };

    const loadKnowledgeBases = async () => {
      try {
        const res = await apiFetch(apiUrl("/api/v1/knowledge/list"));
        if (!res.ok) return;
        const data = (await res.json()) as KnowledgeBaseInfo[];
        const list = Array.isArray(data) ? data : [];
        setKnowledgeBases(list);

        const preferred = list.find((item) => item.is_default) || list[0];
        if (preferred) {
          setRagKbName((prev) => prev || preferred.name);
        }
      } catch (fetchError) {
        console.error("Failed to load knowledge bases:", fetchError);
      }
    };

    loadWorkflowTemplates();
    loadLlmOptions();
    loadKnowledgeBases();
  }, []);

  const onFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(event.target.files || []);
    setFiles(selected);
  };

  const handleImportFromNotebook = (content: string, records: NotebookRecord[]) => {
    setSourceText((prev) =>
      prev.trim() ? `${prev}\n\n${content.trim()}` : content.trim(),
    );
    // Note: We deliberately do not store records as materials here 
    // to prevent duplication, since they are already appended to sourceText.
  };

  const handleTemplateChange = (templateId: string) => {
    setSelectedTemplateId(templateId);
    const nextTemplate =
      selectedWorkflow.templates.find((template) => template.id === templateId) ||
      getDefaultTemplate(selectedWorkflow);
    setSettings(cloneTemplateSettings(nextTemplate));
  };

  const updateSetting = (key: string, value: SettingsValue) => {
    setSettings((prev) => ({
      ...prev,
      [key]: value,
    }));
  };

  const applyStyleDirectivePreset = (presetId: string) => {
    const preset = SLIDE_STYLE_DIRECTIVE_PRESETS.find((item) => item.id === presetId);
    if (!preset) return;
    updateSetting("style", preset.style);
    updateSetting("style_directives", preset.directives);
  };

  const parseListValue = (raw: string, current: SettingsValue): SettingsValue => {
    const values = raw
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);

    if (Array.isArray(current) && current.every((item) => typeof item === "number")) {
      return values
        .map((item) => Number(item))
        .filter((item) => Number.isFinite(item));
    }

    if (Array.isArray(current) && current.every((item) => typeof item === "boolean")) {
      return values.map((item) => item.toLowerCase() === "true");
    }

    return values;
  };

  const uploadArtifacts = useCallback(
    async (uploadFiles: File[], manifest?: Record<string, unknown>) => {
      if (!result?.run_id || uploadFiles.length === 0) return;

      const formData = new FormData();
      uploadFiles.forEach((file) => formData.append("files", file));
      if (manifest) {
        formData.append("manifest", JSON.stringify(manifest));
      }

      const response = await apiFetch(
        apiUrl(`/api/v1/edu-studio/runs/${result.run_id}/artifacts`),
        {
          method: "POST",
          body: formData,
        },
      );
      const data = (await readApiResponse(response)) as ArtifactUploadResponse | { detail?: string };
      if (!response.ok || !(data as ArtifactUploadResponse).success) {
        const detail = (data as { detail?: string }).detail || "Artifact upload failed.";
        throw new Error(detail);
      }

      const payload = data as ArtifactUploadResponse;
      setResult((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          artifacts: uniqueArtifacts(prev.artifacts || [], payload.artifacts || []),
        };
      });
    },
    [result],
  );

  const handleRun = async () => {
    setError("");
    setResult(null);
    setArtifactNotice("");

    if (enableRag && !ragKbName) {
      setError("Please select a Knowledge Base before enabling RAG enrichment.");
      return;
    }

    const contextEnrichment: ContextEnrichmentConfig = {
      enable_rag: enableRag,
      kb_name: ragKbName,
      rag_mode: ragMode,
      enable_web_search: enableWebSearch,
      search_mode: searchMode,
      search_provider: searchProvider === "default" ? "" : searchProvider,
    };

    const payload: EduStudioRunRequest = {
      workflow,
      title,
      language,
      source_text: sourceText,
      instructions,
      settings,
      settings_template: selectedTemplateId,
      context_enrichment: contextEnrichment,
      model_config_id: modelConfigId,
      materials: [], // Materials omitted to avoid deduplication with sourceText
    };

    setLoading(true);
    try {
      let response: Response;
      if (files.length > 0) {
        const formData = new FormData();
        formData.append("payload", JSON.stringify(payload));
        files.forEach((file) => formData.append("files", file));

        response = await apiFetch(apiUrl("/api/v1/edu-studio/run-with-files"), {
          method: "POST",
          body: formData,
        });
      } else {
        response = await apiFetch(apiUrl("/api/v1/edu-studio/run"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      }

      const data = (await readApiResponse(response)) as EduStudioRunResponse | { detail?: string };
      if (!response.ok || !(data as EduStudioRunResponse).success) {
        throw new Error((data as { detail?: string }).detail || "Failed to run workflow");
      }
      setResult(data as EduStudioRunResponse);
    } catch (runError: unknown) {
      const message = runError instanceof Error ? runError.message : "Failed to run workflow.";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  const copyMarkdown = async () => {
    if (!result?.result?.deliverable_markdown) return;
    try {
      await navigator.clipboard.writeText(result.result.deliverable_markdown);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      setError("Clipboard not available in this browser.");
    }
  };

  const downloadFile = (filename: string, content: string, mime: string) => {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const captureSlides = useCallback(async () => {
    if (!slideNodes.length) {
      throw new Error("Slide preview is not ready yet.");
    }
    return captureSlidesAsPng(slideNodes, `${result?.run_id || "slide"}`);
  }, [slideNodes, result?.run_id]);

  const handleExportImages = async () => {
    if (!result?.run_id) {
      setError("Run the slide workflow first.");
      return;
    }

    setExporting("images");
    setArtifactNotice("");
    setError("");
    try {
      const slides = await captureSlides();
      const zipBlob = await buildSlidesZip(slides);
      const zipName = `${result.run_id}_slides.zip`;
      downloadBlob(zipBlob, zipName);

      const pngFiles = slides.map((slide) => blobToFile(slide.blob, slide.fileName, "image/png"));
      const zipFile = blobToFile(zipBlob, zipName, "application/zip");

      await uploadArtifacts([...pngFiles, zipFile], {
        kind: "slide_images",
        slide_count: slides.length,
      });
      setArtifactNotice("Slides exported as PNG+ZIP and uploaded to server artifacts.");
    } catch (exportError: unknown) {
      const message =
        exportError instanceof Error ? exportError.message : "Failed to export slide images.";
      setError(message);
    } finally {
      setExporting(null);
    }
  };

  const handleExportPdf = async () => {
    if (!result?.run_id) {
      setError("Run the slide workflow first.");
      return;
    }

    setExporting("pdf");
    setArtifactNotice("");
    setError("");
    try {
      const slides = await captureSlides();
      const pdfBlob = await buildSlidesPdf(slides);
      const fileName = `${result.run_id}_slides.pdf`;
      downloadBlob(pdfBlob, fileName);
      await uploadArtifacts([blobToFile(pdfBlob, fileName, "application/pdf")], {
        kind: "slide_pdf",
        slide_count: slides.length,
      });
      setArtifactNotice("PDF exported and uploaded to server artifacts.");
    } catch (exportError: unknown) {
      const message =
        exportError instanceof Error ? exportError.message : "Failed to export PDF.";
      setError(message);
    } finally {
      setExporting(null);
    }
  };

  const handleExportPptx = async () => {
    if (!result?.run_id) {
      setError("Run the slide workflow first.");
      return;
    }

    setExporting("pptx");
    setArtifactNotice("");
    setError("");
    try {
      const slides = await captureSlides();
      const pptxBlob = await buildSlidesPptx(slides);
      const fileName = `${result.run_id}_slides.pptx`;
      downloadBlob(pptxBlob, fileName);
      await uploadArtifacts(
        [
          blobToFile(
            pptxBlob,
            fileName,
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
          ),
        ],
        {
          kind: "slide_pptx",
          slide_count: slides.length,
          mode: "image-based",
        },
      );
      setArtifactNotice("PowerPoint exported and uploaded to server artifacts.");
    } catch (exportError: unknown) {
      const message =
        exportError instanceof Error ? exportError.message : "Failed to export PowerPoint.";
      setError(message);
    } finally {
      setExporting(null);
    }
  };

  return (
    <div className="h-screen p-4 animate-fade-in flex flex-col lg:flex-row gap-4 overflow-hidden">
      <div className="lg:w-[420px] w-full bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-sm flex flex-col overflow-hidden">
        <div className="p-4 border-b border-slate-100 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-800/60">
          <div className="flex items-start justify-between gap-2">
            <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
              Edu Studio
            </h1>
            <Link
              href="/edu_studio/qwen_teacher"
              className="inline-flex items-center gap-1 text-[11px] px-2.5 py-1 rounded-md border border-emerald-200 dark:border-emerald-700 bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-100 dark:hover:bg-emerald-900/50 transition-colors whitespace-nowrap"
            >
              Qwen-Teacher Model
              <ArrowUpRight className="w-3 h-3" />
            </Link>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Multi-agent education workflows (slides, exam matrix, lesson plans, and more)
          </p>
        </div>

        <div className="p-4 space-y-4 overflow-y-auto flex-1">
          <div>
            <label className="text-xs uppercase tracking-wider font-bold text-slate-500 dark:text-slate-400">
              Workflow
            </label>
            <select
              value={workflow}
              onChange={(event) => {
                const next = event.target.value as WorkflowType;
                const template = getDefaultTemplate(availableWorkflows.find(item => item.id === next));
                setWorkflow(next); setSelectedTemplateId(template?.id || "");
                setSettings({ style_directives: "", ...cloneTemplateSettings(template) });
              }}
              className="mt-1 w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
            >
              {availableWorkflows.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              {selectedWorkflow.description}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs uppercase tracking-wider font-bold text-slate-500 dark:text-slate-400">
                Language
              </label>
              <select
                value={language}
                onChange={(event) => setLanguage(event.target.value as "vi" | "en")}
                className="mt-1 w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
              >
                <option value="vi">Vietnamese</option>
                <option value="en">English</option>
              </select>
            </div>
            <div>
              <label className="text-xs uppercase tracking-wider font-bold text-slate-500 dark:text-slate-400">
                Model Option
              </label>
              <select
                value={modelConfigId}
                onChange={(event) => setModelConfigId(event.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
              >
                <option value="active">Active Model</option>
                <option value="default">Default (.env)</option>
                {llmOptions.map((cfg) => (
                  <option key={cfg.id} value={cfg.id}>
                    {cfg.name === "Qwen-Teacher (.env)"
                      ? `${cfg.name} (${cfg.model})${cfg.metadata?.device ? ` • ${cfg.metadata.device}` : ""}`
                      : `${cfg.name} (${cfg.model})`}
                  </option>
                ))}
              </select>
              {modelConfigId === QWEN_TEACHER_CONFIG_ID && (
                <p className="mt-1 text-[11px] text-emerald-700 dark:text-emerald-300">
                  Uses `VNM_TEACHER_PROVIDER`, `VNM_TEACHER_MODEL`, `VNM_TEACHER_DEVICE` from `.env`.
                </p>
              )}
            </div>
          </div>

          <div>
            <label className="text-xs uppercase tracking-wider font-bold text-slate-500 dark:text-slate-400">
              Title
            </label>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Optional title"
              className="mt-1 w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
            />
          </div>

          <div>
            <div className="flex items-center justify-between">
              <label className="text-xs uppercase tracking-wider font-bold text-slate-500 dark:text-slate-400">
                Source Materials
              </label>
              <button
                onClick={() => setShowNotebookImport(true)}
                className="text-xs px-2 py-1 rounded-md border border-slate-200 dark:border-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
              >
                <BookOpen className="w-3 h-3 inline mr-1" />
                Import Notebook
              </button>
            </div>
            <textarea
              value={sourceText}
              onChange={(event) => setSourceText(event.target.value)}
              rows={7}
              placeholder="Paste lesson content, matrix constraints, sample template, or supporting material..."
              className="mt-1 w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20 resize-none"
            />
          </div>

          <div>
            <label className="text-xs uppercase tracking-wider font-bold text-slate-500 dark:text-slate-400">
              Additional Instructions
            </label>
            <textarea
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
              rows={3}
              placeholder="Extra constraints, tone, formatting, or compliance rules..."
              className="mt-1 w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20 resize-none"
            />
          </div>

          <div>
            <div className="flex items-center justify-between">
              <label className="text-xs uppercase tracking-wider font-bold text-slate-500 dark:text-slate-400">
                Settings Template
              </label>
              <span className="text-[11px] text-slate-500 dark:text-slate-400">
                Key set is template-locked
              </span>
            </div>
            <select
              value={selectedTemplateId}
              onChange={(event) => handleTemplateChange(event.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-sm text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
            >
              {selectedWorkflow.templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                </option>
              ))}
            </select>
            {selectedTemplate && (
              <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                {selectedTemplate.description}
              </p>
            )}

            <div className="mt-3 space-y-2">
              {Object.entries(settings).map(([key, value]) => {
                const label = key.replaceAll("_", " ");
                const fieldKey = `${selectedTemplateId}-${key}`;
                const isLongText =
                  typeof value === "string" &&
                  (value.length > 80 ||
                    key.includes("definition") ||
                    key.includes("requirements") ||
                    key.includes("template") ||
                    key.includes("directives"));

                return (
                  <div key={fieldKey}>
                    <label className="block text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1">
                      {label}
                    </label>

                    {Array.isArray(value) ? (
                      <input
                        value={value.join(", ")}
                        onChange={(event) =>
                          updateSetting(key, parseListValue(event.target.value, value))
                        }
                        placeholder="Comma-separated values"
                        className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
                      />
                    ) : typeof value === "boolean" ? (
                      <select
                        value={value ? "true" : "false"}
                        onChange={(event) => updateSetting(key, event.target.value === "true")}
                        className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
                      >
                        <option value="true">true</option>
                        <option value="false">false</option>
                      </select>
                    ) : typeof value === "number" ? (
                      <input
                        type="number"
                        value={value}
                        onChange={(event) => {
                          const parsed = Number(event.target.value);
                          if (Number.isFinite(parsed)) {
                            updateSetting(key, parsed);
                          }
                        }}
                        className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
                      />
                    ) : workflow === "slide_deck" && key === "style" ? (
                      <select
                        value={String(value ?? "")}
                        onChange={(event) => updateSetting(key, event.target.value)}
                        className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
                      >
                        {SLIDE_STYLE_OPTIONS.map((styleOption) => (
                          <option key={styleOption.id} value={styleOption.id}>
                            {styleOption.label}
                          </option>
                        ))}
                      </select>
                    ) : isLongText ? (
                      <textarea
                        value={String(value ?? "")}
                        onChange={(event) => updateSetting(key, event.target.value)}
                        rows={3}
                        className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20 resize-none"
                      />
                    ) : (
                      <input
                        value={String(value ?? "")}
                        onChange={(event) => updateSetting(key, event.target.value)}
                        className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
                      />
                    )}
                  </div>
                );
              })}
            </div>

            {workflow === "slide_deck" && (
              <div className="mt-3 rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50/60 dark:bg-slate-900/40 p-3">
                <label className="block text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-2">
                  Style Directive Preset
                </label>
                <select
                  defaultValue=""
                  onChange={(event) => {
                    const presetId = event.target.value;
                    if (presetId) applyStyleDirectivePreset(presetId);
                    event.target.value = "";
                  }}
                  className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-3 py-2 text-xs text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
                >
                  <option value="">Select preset to auto-fill style directives...</option>
                  {SLIDE_STYLE_DIRECTIVE_PRESETS.map((preset) => (
                    <option key={preset.id} value={preset.id}>
                      {preset.label}
                    </option>
                  ))}
                </select>
                <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">
                  Preset will update both <code>style</code> and <code>style_directives</code>.
                </p>
              </div>
            )}
          </div>

          <div className="rounded-xl border border-slate-200 dark:border-slate-600 bg-slate-50/70 dark:bg-slate-900/40 p-3 space-y-3">
            <label className="text-xs uppercase tracking-wider font-bold text-slate-500 dark:text-slate-400">
              Context Enrichment (RAG + Search)
            </label>

            <div className="flex items-center justify-between gap-3">
              <label className="text-xs text-slate-700 dark:text-slate-300 inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={enableRag}
                  onChange={(event) => setEnableRag(event.target.checked)}
                  className="rounded border-slate-300 dark:border-slate-500"
                />
                Enable RAG
              </label>

              <label className="text-xs text-slate-700 dark:text-slate-300 inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={enableWebSearch}
                  onChange={(event) => setEnableWebSearch(event.target.checked)}
                  className="rounded border-slate-300 dark:border-slate-500"
                />
                Enable Web Search
              </label>
            </div>

            {enableRag && (
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1">
                    Knowledge Base
                  </label>
                  <select
                    value={ragKbName}
                    onChange={(event) => setRagKbName(event.target.value)}
                    className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-2 py-2 text-xs text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
                  >
                    {knowledgeBases.length === 0 && <option value="">No KB available</option>}
                    {knowledgeBases.map((kb) => (
                      <option key={kb.name} value={kb.name}>
                        {kb.name}
                        {kb.is_default ? " (default)" : ""}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1">
                    RAG Mode
                  </label>
                  <select
                    value={ragMode}
                    onChange={(event) => setRagMode(event.target.value as RAGMode)}
                    className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-2 py-2 text-xs text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
                  >
                    <option value="hybrid">hybrid</option>
                    <option value="local">local</option>
                    <option value="global">global</option>
                    <option value="naive">naive</option>
                  </select>
                </div>
              </div>
            )}

            {enableWebSearch && (
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1">
                    Search Mode
                  </label>
                  <select
                    value={searchMode}
                    onChange={(event) => setSearchMode(event.target.value as SearchMode)}
                    className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-2 py-2 text-xs text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
                  >
                    <option value="quick">quick</option>
                    <option value="balanced">balanced</option>
                    <option value="deep">deep</option>
                  </select>
                </div>
                <div>
                  <label className="block text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1">
                    Search Provider
                  </label>
                  <select
                    value={searchProvider}
                    onChange={(event) => setSearchProvider(event.target.value)}
                    className="w-full rounded-lg border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 px-2 py-2 text-xs text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-emerald-500/20"
                  >
                    {SEARCH_PROVIDER_OPTIONS.map((provider) => (
                      <option key={provider.id} value={provider.id}>
                        {provider.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            )}

            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              RAG/Search context will be appended to source materials so the model can expand
              examples and evidence for higher-quality slides.
            </p>
            {ragUnavailable && (
              <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-2 text-[11px] text-amber-700 dark:text-amber-300">
                Selected KB appears not fully initialized for RAG (
                {selectedKnowledgeBase?.statistics?.status || "unknown"}). Edu Studio will use
                local excerpt fallback; run KB processing for stronger retrieval quality.
              </div>
            )}
          </div>

          <div>
            <label className="text-xs uppercase tracking-wider font-bold text-slate-500 dark:text-slate-400">
              Upload Files
            </label>
            <label className="mt-1 flex items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900 px-3 py-3 cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-800">
              <Upload className="w-4 h-4 text-slate-500 dark:text-slate-400" />
              <span className="text-xs text-slate-600 dark:text-slate-300">
                Select .txt/.md/.json/.csv/.pdf/.docx files
              </span>
              <input
                type="file"
                multiple
                onChange={onFileChange}
                className="hidden"
                accept=".txt,.md,.json,.csv,.tsv,.pdf,.docx"
              />
            </label>
            {files.length > 0 && (
              <div className="mt-2 text-xs text-slate-500 dark:text-slate-400 space-y-1">
                {files.map((file) => (
                  <div key={file.name}>• {file.name}</div>
                ))}
              </div>
            )}
          </div>

          {error && (
            <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/30 px-3 py-2 text-xs text-red-700 dark:text-red-300 flex gap-2">
              <AlertTriangle className="w-4 h-4 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {artifactNotice && (
            <div className="rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-900/30 px-3 py-2 text-xs text-emerald-700 dark:text-emerald-300">
              {artifactNotice}
            </div>
          )}
        </div>

        <div className="p-4 border-t border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/60">
          <button
            onClick={handleRun}
            disabled={loading}
            className="w-full rounded-lg bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white font-semibold py-2.5 text-sm flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Running Workflow...
              </>
            ) : (
              <>
                <Play className="w-4 h-4" />
                Run {selectedWorkflow.name}
              </>
            )}
          </button>
        </div>
      </div>

      <div className="flex-1 bg-white dark:bg-slate-800 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-sm flex flex-col overflow-hidden">
        <div className="p-4 border-b border-slate-100 dark:border-slate-700 bg-slate-50/70 dark:bg-slate-800/60 flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold text-slate-900 dark:text-slate-100 flex items-center gap-2">
              <FileText className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              Workflow Output
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              Structured output + markdown deliverable + quality checks
            </p>
          </div>
          {result?.result && (
            <div className="flex items-center gap-2">
              <button
                onClick={copyMarkdown}
                className="px-3 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 flex items-center gap-1.5"
              >
                {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
                {copied ? "Copied" : "Copy"}
              </button>
              <button
                onClick={() =>
                  downloadFile(
                    `${result.workflow || "edu_studio"}.md`,
                    result.result.deliverable_markdown || "",
                    "text/markdown",
                  )
                }
                className="px-3 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 flex items-center gap-1.5"
              >
                <Download className="w-3.5 h-3.5" />
                Markdown
              </button>
              <button
                onClick={() =>
                  downloadFile(
                    `${result.workflow || "edu_studio"}.json`,
                    JSON.stringify(result.result, null, 2),
                    "application/json",
                  )
                }
                className="px-3 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 flex items-center gap-1.5"
              >
                <Settings2 className="w-3.5 h-3.5" />
                JSON
              </button>
            </div>
          )}
        </div>

        <div className="p-5 overflow-y-auto flex-1">
          {!result?.result ? (
            <div className="h-full flex flex-col items-center justify-center text-slate-400 dark:text-slate-500">
              <Sparkles className="w-10 h-10 mb-3 opacity-40" />
              <p className="text-sm">Run a workflow to see generated output.</p>
            </div>
          ) : (
            <div className="space-y-5">
              <div className="rounded-xl border border-slate-200 dark:border-slate-700 p-4 bg-slate-50/60 dark:bg-slate-900/40">
                <h3 className="font-bold text-slate-900 dark:text-slate-100">{result.result.title}</h3>
                <p className="text-sm text-slate-600 dark:text-slate-300 mt-1">{result.result.summary}</p>
                {result.result.metadata && (
                  <div className="mt-3 text-xs text-slate-500 dark:text-slate-400 space-y-1">
                    <div>
                      Model: {result.result.metadata.model} | Provider: {result.result.metadata.provider}
                    </div>
                    <div>Run ID: {result.run_id}</div>
                    {result.context_enrichment && (
                      <div>
                        Enrichment:{" "}
                        {Boolean(result.context_enrichment.applied)
                          ? "Applied"
                          : "Disabled / No external context"}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {workflow === "slide_deck" && slideDeckData && (
                <div className="rounded-xl border border-slate-200 dark:border-slate-700 p-4 space-y-4">
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                      Slide Preview & Export
                    </h4>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={handleExportImages}
                        disabled={exporting !== null}
                        className="px-3 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 disabled:opacity-50 text-slate-700 dark:text-slate-300 flex items-center gap-1.5"
                      >
                        {exporting === "images" ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <ImageIcon className="w-3.5 h-3.5" />
                        )}
                        Download Images (.zip)
                      </button>
                      <button
                        onClick={handleExportPdf}
                        disabled={exporting !== null}
                        className="px-3 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 disabled:opacity-50 text-slate-700 dark:text-slate-300 flex items-center gap-1.5"
                      >
                        {exporting === "pdf" ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <FileDown className="w-3.5 h-3.5" />
                        )}
                        Export PDF
                      </button>
                      <button
                        onClick={handleExportPptx}
                        disabled={exporting !== null}
                        className="px-3 py-1.5 text-xs rounded-lg border border-slate-200 dark:border-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 disabled:opacity-50 text-slate-700 dark:text-slate-300 flex items-center gap-1.5"
                      >
                        {exporting === "pptx" ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Presentation className="w-3.5 h-3.5" />
                        )}
                        Export PowerPoint
                      </button>
                    </div>
                  </div>

                  <SlideDeckPreview
                    deck={slideDeckData}
                    onSlidesReady={(nodes) => setSlideNodes(nodes)}
                  />
                </div>
              )}

              {Array.isArray(result.artifacts) && result.artifacts.length > 0 && (
                <div className="rounded-xl border border-slate-200 dark:border-slate-700 p-4 space-y-2">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                    Persisted Artifacts
                  </h4>
                  <div className="space-y-1 text-xs text-slate-600 dark:text-slate-300">
                    {result.artifacts.map((artifact, index) => (
                      <a
                        key={`${artifact.url}-${index}`}
                        href={artifact.url}
                        target="_blank"
                        rel="noreferrer"
                        className="block hover:underline"
                      >
                        {artifact.file_name} ({Math.max(1, Math.round(artifact.size_bytes / 1024))} KB)
                      </a>
                    ))}
                  </div>
                </div>
              )}

              {Array.isArray(result.result.quality_checks) &&
                result.result.quality_checks.length > 0 && (
                  <div className="space-y-2">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                      Quality Checks
                    </h4>
                    <div className="grid md:grid-cols-2 gap-2">
                      {result.result.quality_checks.map((item, idx) => (
                        <div
                          key={`${item.name}-${idx}`}
                          className={`rounded-lg border px-3 py-2 text-xs ${
                            item.status === "pass"
                              ? "border-emerald-200 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300"
                              : item.status === "warn"
                                ? "border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300"
                                : item.status === "error" || item.status === "fail"
                                  ? "border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-900/30 text-red-700 dark:text-red-300"
                                  : "border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-900/30 text-slate-700 dark:text-slate-300"
                          }`}
                        >
                          <div className="font-semibold">{item.name}</div>
                          <div>{item.detail}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

              {Array.isArray(result.warnings) && result.warnings.length > 0 && (
                <div className="rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 p-3 text-xs text-amber-700 dark:text-amber-300">
                  <div className="font-semibold mb-1">Warnings</div>
                  <ul className="list-disc pl-4 space-y-1">
                    {result.warnings.map((warning, idx) => (
                      <li key={`${warning}-${idx}`}>{warning}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="rounded-xl border border-slate-200 dark:border-slate-700 p-4">
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3">
                  Deliverable
                </h4>
                <MarkdownRenderer
                  content={result.result.deliverable_markdown || ""}
                  variant="prose"
                />
              </div>

              <details className="rounded-xl border border-slate-200 dark:border-slate-700 p-4">
                <summary className="cursor-pointer text-sm font-semibold text-slate-800 dark:text-slate-200">
                  Structured Data
                </summary>
                <pre className="mt-3 text-xs text-slate-700 dark:text-slate-300 overflow-x-auto bg-slate-50 dark:bg-slate-900 p-3 rounded-lg">
                  {JSON.stringify(result.result.structured_data || {}, null, 2)}
                </pre>
              </details>
            </div>
          )}
        </div>
      </div>

      <NotebookImportModal
        isOpen={showNotebookImport}
        onClose={() => setShowNotebookImport(false)}
        onImport={handleImportFromNotebook}
        title="Import records from notebooks"
      />
    </div>
  );
}
