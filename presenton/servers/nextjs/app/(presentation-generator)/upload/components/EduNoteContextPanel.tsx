"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, Search, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { withBasePath } from "@/utils/basePath";

interface EduNoteContextPanelProps {
  prompt: string;
  onPromptChange: (nextPrompt: string) => void;
}

interface NotebookSummary {
  id: string;
  name: string;
  record_count?: number;
}

interface NotebookListResponse {
  notebooks?: NotebookSummary[];
}

interface NotebookRecord {
  id?: string;
  type?: string;
  title?: string;
  user_query?: string;
  output?: string;
  created_at?: number;
}

interface NotebookDetails {
  id: string;
  name: string;
  records?: NotebookRecord[];
}

interface KnowledgeBaseSummary {
  name: string;
}

interface KnowledgeChunk {
  chunk_id?: string;
  content?: string;
  doc_name?: string;
  page_start?: number | null;
  page_end?: number | null;
}

interface KnowledgeChunksResponse {
  chunks?: KnowledgeChunk[];
}

const NOTEBOOK_SECTION_START = "[EDUNOTE_NOTEBOOK_CONTEXT_START]";
const NOTEBOOK_SECTION_END = "[EDUNOTE_NOTEBOOK_CONTEXT_END]";
const KB_SECTION_START = "[EDUNOTE_KB_CONTEXT_START]";
const KB_SECTION_END = "[EDUNOTE_KB_CONTEXT_END]";
const STOP_WORDS = new Set([
  "the",
  "and",
  "for",
  "with",
  "from",
  "into",
  "this",
  "that",
  "your",
  "their",
  "have",
  "has",
  "will",
  "are",
  "was",
  "were",
  "about",
  "use",
  "using",
  "slide",
  "slides",
  "presentation",
  "context",
  "query",
  "record",
  "records",
  "knowledge",
  "base",
  "retrieval",
  "chunk",
  "chunks",
]);
const EXPLICIT_EDUNOTE_API_BASE = (process.env.NEXT_PUBLIC_EDUNOTE_API_BASE || "").replace(
  /\/+$/,
  "",
);

function dedupe(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

function deriveBackendOrigin(origin: string): string {
  try {
    const url = new URL(origin);
    if (url.hostname.startsWith("edunote.")) {
      url.hostname = url.hostname.replace(/^edunote\./, "backend.");
      return url.origin;
    }
  } catch {
    return "";
  }
  return "";
}

function getEduNoteApiCandidates(path: string): string[] {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const proxyCandidate = withBasePath(`/edunote-api${normalizedPath}`);
  if (EXPLICIT_EDUNOTE_API_BASE) {
    return dedupe([proxyCandidate, `${EXPLICIT_EDUNOTE_API_BASE}${normalizedPath}`]);
  }

  if (typeof window === "undefined") {
    return [proxyCandidate];
  }

  const candidates: string[] = [proxyCandidate];

  const currentOrigin = window.location.origin;
  const derivedBackend = deriveBackendOrigin(currentOrigin);
  if (derivedBackend) {
    candidates.push(`${derivedBackend}${normalizedPath}`);
  } else {
    const currentHost = window.location.hostname;
    if (currentHost === "localhost" || currentHost === "127.0.0.1") {
      candidates.push(`${currentOrigin}${normalizedPath}`);
    }
  }

  return dedupe(candidates);
}

async function fetchEduNoteJson<T>(path: string, init?: RequestInit): Promise<T> {
  const candidates = getEduNoteApiCandidates(path);
  let lastError: Error | null = null;

  for (const candidate of candidates) {
    try {
      const response = await fetch(candidate, {
        ...init,
        cache: "no-store",
        credentials: "omit",
      });

      if (response.status === 404) {
        continue;
      }

      if (!response.ok) {
        const body = await response.text().catch(() => "");
        throw new Error(body || `${candidate} returned ${response.status}`);
      }

      return (await response.json()) as T;
    } catch (error) {
      lastError =
        error instanceof Error ? error : new Error("Unknown error while loading EduNote sources");
    }
  }

  throw lastError || new Error(`Unable to load ${path}`);
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function stripSection(content: string, startTag: string, endTag: string): string {
  const sectionRegex = new RegExp(
    `${escapeRegExp(startTag)}[\\s\\S]*?${escapeRegExp(endTag)}\\s*`,
    "g",
  );
  return content.replace(sectionRegex, "").trim();
}

function upsertSection(content: string, startTag: string, endTag: string, sectionBody: string): string {
  const cleanContent = stripSection(content, startTag, endTag);
  if (!sectionBody.trim()) return cleanContent;
  return `${cleanContent}\n\n${startTag}\n${sectionBody.trim()}\n${endTag}`.trim();
}

function normalizeText(value: string | undefined, maxChars: number): string {
  if (!value) return "";
  const squashed = value.replace(/\s+/g, " ").trim();
  if (!squashed) return "";
  return squashed.length > maxChars ? `${squashed.slice(0, maxChars)}...` : squashed;
}

function getRecordKey(record: NotebookRecord, index: number): string {
  return record.id || `record-${index}`;
}

function isLikelyVietnamese(text: string): boolean {
  return /[À-ỹà-ỹđĐ]/.test(text);
}

function extractQuotedTopic(text: string): string {
  const matches = Array.from(text.matchAll(/["“”'‘’]([^"“”'‘’]{4,140})["“”'‘’]/g))
    .map((item) => (item[1] || "").trim())
    .filter(Boolean);
  return matches[0] || "";
}

function compactTopic(text: string): string {
  const normalized = text
    .replace(/\s+/g, " ")
    .replace(/^[\-\•\d\.\)\s]+/, "")
    .replace(
      /^(làm bài thuyết trình|viết|tạo|generate|create|make|build)\s+(về|about|on)\s+/i,
      "",
    )
    .replace(/\b(trong năm|giai đoạn|for|in)\s+20\d{2}(?:\s*[-–]\s*20\d{2})?/gi, "")
    .trim();

  return normalizeText(normalized, 90);
}

function extractYears(text: string): string[] {
  return dedupe((text.match(/\b20\d{2}\b/g) || []).slice(0, 3));
}

function buildRetrievalQueries(prompt: string): string[] {
  const cleanPrompt = stripSection(
    stripSection(prompt, NOTEBOOK_SECTION_START, NOTEBOOK_SECTION_END),
    KB_SECTION_START,
    KB_SECTION_END,
  ).trim();
  if (!cleanPrompt) return [];

  const lines = cleanPrompt
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
  const quotedTopic = extractQuotedTopic(cleanPrompt);
  const firstLine = compactTopic(lines[0] || "");

  const tokens = (cleanPrompt.toLowerCase().match(/[a-zA-ZÀ-ỹ0-9][a-zA-ZÀ-ỹ0-9_-]{2,}/g) || [])
    .filter((token) => !STOP_WORDS.has(token) && !/^\d+$/.test(token));

  const tokenFrequency = new Map<string, number>();
  for (const token of tokens) {
    tokenFrequency.set(token, (tokenFrequency.get(token) || 0) + 1);
  }

  const topTerms = Array.from(tokenFrequency.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([token]) => token);

  const keywordTopic = normalizeText(topTerms.slice(0, 4).join(" "), 60);
  const topic = quotedTopic || firstLine || keywordTopic || "current topic";
  const years = extractYears(cleanPrompt);
  const yearHint = years.length > 0 ? ` ${years.join("-")}` : "";
  const focusTerms = topTerms.length > 0 ? ` ${topTerms.slice(0, 3).join(", ")}` : "";
  const isVietnamese = isLikelyVietnamese(cleanPrompt);

  const candidates = isVietnamese
    ? [
        `${topic}${yearHint} khái niệm cốt lõi và định nghĩa`,
        `${topic}${yearHint} số liệu thống kê thị trường việc làm`,
        `${topic}${yearHint} ứng dụng thực tế và case study`,
        `${topic}${yearHint} kỹ năng bị thay thế và kỹ năng mới cần có`,
        `${topic}${yearHint} tác động theo ngành nghề và mức lương`,
        `${topic}${yearHint} thách thức, rủi ro, chính sách và xu hướng tương lai${focusTerms}`,
      ]
    : [
        `${topic}${yearHint} core concepts and definitions`,
        `${topic}${yearHint} labor market statistics and benchmarks`,
        `${topic}${yearHint} job displacement versus job creation evidence`,
        `${topic}${yearHint} impact by industry, role, and salary band`,
        `${topic}${yearHint} reskilling, policy response, and workforce strategy`,
        `${topic}${yearHint} limitations, risks, and future directions${focusTerms}`,
      ];

  return dedupe(
    candidates
      .map((query) => normalizeText(query, 140))
      .filter((query) => query.length > 8),
  ).slice(0, 6);
}

export default function EduNoteContextPanel({ prompt, onPromptChange }: EduNoteContextPanelProps) {
  const [notebooks, setNotebooks] = useState<NotebookSummary[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseSummary[]>([]);
  const [selectedNotebookId, setSelectedNotebookId] = useState("");
  const [selectedKnowledgeBase, setSelectedKnowledgeBase] = useState("");
  const [notebookDetails, setNotebookDetails] = useState<NotebookDetails | null>(null);
  const [selectedRecordKeys, setSelectedRecordKeys] = useState<string[]>([]);
  const [activeRecordKey, setActiveRecordKey] = useState("");
  const [knowledgeQuery, setKnowledgeQuery] = useState("");
  const [generatedQueries, setGeneratedQueries] = useState<string[]>([]);
  const [selectedGeneratedQueries, setSelectedGeneratedQueries] = useState<string[]>([]);
  const [knowledgeChunkLimit, setKnowledgeChunkLimit] = useState(5);
  const [isLoadingOptions, setIsLoadingOptions] = useState(false);
  const [isLoadingNotebookRecords, setIsLoadingNotebookRecords] = useState(false);
  const [isImportingNotebook, setIsImportingNotebook] = useState(false);
  const [isGeneratingQueries, setIsGeneratingQueries] = useState(false);
  const [isRetrievingKnowledge, setIsRetrievingKnowledge] = useState(false);

  const hasImportedNotebookContext = useMemo(
    () => prompt.includes(NOTEBOOK_SECTION_START) && prompt.includes(NOTEBOOK_SECTION_END),
    [prompt],
  );
  const hasImportedKnowledgeContext = useMemo(
    () => prompt.includes(KB_SECTION_START) && prompt.includes(KB_SECTION_END),
    [prompt],
  );
  const notebookRecordOptions = useMemo(() => {
    const records = Array.isArray(notebookDetails?.records) ? notebookDetails.records : [];
    return records.map((record, index) => ({
      key: getRecordKey(record, index),
      record,
      index,
    }));
  }, [notebookDetails]);
  const selectedNotebookRecords = useMemo(() => {
    if (selectedRecordKeys.length === 0) return [];
    const selectedSet = new Set(selectedRecordKeys);
    return notebookRecordOptions
      .filter((item) => selectedSet.has(item.key))
      .map((item) => item.record);
  }, [notebookRecordOptions, selectedRecordKeys]);
  const activeNotebookRecord = useMemo(() => {
    const activeMatch = notebookRecordOptions.find((item) => item.key === activeRecordKey);
    if (activeMatch) return activeMatch.record;
    if (selectedNotebookRecords.length > 0) return selectedNotebookRecords[0];
    if (notebookRecordOptions.length > 0) {
      return notebookRecordOptions[notebookRecordOptions.length - 1].record;
    }
    return null;
  }, [activeRecordKey, notebookRecordOptions, selectedNotebookRecords]);

  useEffect(() => {
    let isCancelled = false;

    const loadSources = async () => {
      setIsLoadingOptions(true);
      try {
        const [notebookResponse, knowledgeResponse] = await Promise.all([
          fetchEduNoteJson<NotebookListResponse>("/api/v1/notebook/list"),
          fetchEduNoteJson<KnowledgeBaseSummary[]>("/api/v1/knowledge/list"),
        ]);

        if (isCancelled) return;

        const notebookList = Array.isArray(notebookResponse?.notebooks)
          ? notebookResponse.notebooks
          : [];
        const kbList = Array.isArray(knowledgeResponse) ? knowledgeResponse : [];

        setNotebooks(notebookList);
        setKnowledgeBases(kbList);

        if (!selectedNotebookId && notebookList.length > 0) {
          setSelectedNotebookId(notebookList[0].id);
        }
        if (!selectedKnowledgeBase && kbList.length > 0) {
          setSelectedKnowledgeBase(kbList[0].name);
        }
      } catch (error) {
        if (!isCancelled) {
          console.error("Failed to load EduNote sources", error);
          toast.error("Unable to load notebook/knowledge sources");
        }
      } finally {
        if (!isCancelled) {
          setIsLoadingOptions(false);
        }
      }
    };

    void loadSources();

    return () => {
      isCancelled = true;
    };
  }, []);

  useEffect(() => {
    let isCancelled = false;

    const loadNotebookRecords = async () => {
      if (!selectedNotebookId) {
        setNotebookDetails(null);
        setSelectedRecordKeys([]);
        setActiveRecordKey("");
        return;
      }

      setIsLoadingNotebookRecords(true);
      try {
        const notebook = await fetchEduNoteJson<NotebookDetails>(
          `/api/v1/notebook/${encodeURIComponent(selectedNotebookId)}`,
        );
        if (isCancelled) return;

        const records = Array.isArray(notebook.records) ? notebook.records : [];
        const options = records.map((record, index) => ({
          key: getRecordKey(record, index),
          record,
        }));
        const latestFiveKeys = options.slice(-Math.min(5, options.length)).map((item) => item.key);

        setNotebookDetails(notebook);
        setSelectedRecordKeys(latestFiveKeys);
        setActiveRecordKey(
          latestFiveKeys[latestFiveKeys.length - 1] ||
            options[options.length - 1]?.key ||
            "",
        );
      } catch (error) {
        if (!isCancelled) {
          console.error("Failed to load notebook details", error);
          toast.error("Unable to load notebook records");
          setNotebookDetails(null);
          setSelectedRecordKeys([]);
          setActiveRecordKey("");
        }
      } finally {
        if (!isCancelled) {
          setIsLoadingNotebookRecords(false);
        }
      }
    };

    void loadNotebookRecords();

    return () => {
      isCancelled = true;
    };
  }, [selectedNotebookId]);

  const handleImportNotebookRecords = async () => {
    if (!selectedNotebookId) {
      toast.error("Please select a notebook");
      return;
    }
    if (selectedNotebookRecords.length === 0) {
      toast.error("Please select at least one record");
      return;
    }

    setIsImportingNotebook(true);
    try {
      const lines = selectedNotebookRecords
        .map((record, idx) => {
          const title = normalizeText(record.title || `Record ${idx + 1}`, 120);
          const query = normalizeText(record.user_query, 240);
          const output = normalizeText(record.output, 850);
          const recordType = normalizeText(record.type, 40);
          return [
            `${idx + 1}. ${title}${recordType ? ` [${recordType}]` : ""}`,
            query ? `Question: ${query}` : "",
            output ? `Content: ${output}` : "",
          ]
            .filter(Boolean)
            .join("\n");
        })
        .join("\n\n");

      const notebookContext = [
        `Notebook: ${notebookDetails?.name || selectedNotebookId}`,
        `Imported records: ${selectedNotebookRecords.length}`,
        "Use the records below as supporting context and evidence for slide content.",
        "",
        lines,
      ].join("\n");

      const nextPrompt = upsertSection(
        prompt,
        NOTEBOOK_SECTION_START,
        NOTEBOOK_SECTION_END,
        notebookContext.slice(0, 7000),
      );
      onPromptChange(nextPrompt);
      toast.success(`Imported ${selectedNotebookRecords.length} notebook records`);
    } catch (error) {
      console.error("Failed to import notebook records", error);
      toast.error("Failed to import notebook records");
    } finally {
      setIsImportingNotebook(false);
    }
  };

  const handleGenerateQueries = () => {
    setIsGeneratingQueries(true);
    try {
      const candidates = buildRetrievalQueries(prompt);
      if (candidates.length === 0) {
        toast.error("Prompt is empty. Add topic details first.");
        return;
      }
      setGeneratedQueries(candidates);
      const defaults = candidates.slice(0, Math.min(3, candidates.length));
      setSelectedGeneratedQueries(defaults);
      if (!knowledgeQuery.trim()) {
        setKnowledgeQuery(candidates[0]);
      }
      toast.success(`Generated ${candidates.length} retrieval queries`);
    } finally {
      setIsGeneratingQueries(false);
    }
  };

  const handleRetrieveKnowledge = async () => {
    if (!selectedKnowledgeBase) {
      toast.error("Please select a knowledge base");
      return;
    }

    const activeQueries =
      selectedGeneratedQueries.length > 0
        ? selectedGeneratedQueries
        : knowledgeQuery.trim()
          ? [knowledgeQuery.trim()]
          : [];
    if (activeQueries.length === 0) {
      toast.error("Please provide a query or generate queries from prompt");
      return;
    }

    setIsRetrievingKnowledge(true);
    try {
      const chunkByKey = new Map<string, KnowledgeChunk & { query: string }>();

      for (const query of activeQueries) {
        const response = await fetchEduNoteJson<KnowledgeChunksResponse>(
          `/api/v1/knowledge/${encodeURIComponent(selectedKnowledgeBase)}/chunks?page=1&page_size=${knowledgeChunkLimit}&search=${encodeURIComponent(query)}`,
        );
        const chunks = (response.chunks || []).slice(0, knowledgeChunkLimit);
        for (const chunk of chunks) {
          const contentPart = normalizeText(chunk.content, 180);
          const uniqueKey = chunk.chunk_id || `${chunk.doc_name || "doc"}|${contentPart}`;
          if (!chunkByKey.has(uniqueKey)) {
            chunkByKey.set(uniqueKey, { ...chunk, query });
          }
        }
      }

      const retrievedChunks = Array.from(chunkByKey.values()).slice(
        0,
        Math.max(knowledgeChunkLimit, activeQueries.length * knowledgeChunkLimit),
      );

      if (retrievedChunks.length === 0) {
        toast.error("No matching knowledge chunks found");
        return;
      }

      const lines = retrievedChunks
        .map((chunk, idx) => {
          const source = normalizeText(chunk.doc_name || chunk.chunk_id || `Chunk ${idx + 1}`, 140);
          const pageInfo =
            chunk.page_start != null
              ? ` (p.${chunk.page_start}${chunk.page_end ? `-${chunk.page_end}` : ""})`
              : "";
          const content = normalizeText(chunk.content, 700);
          return `${idx + 1}. ${source}${pageInfo}\nQuery: ${chunk.query}\nExcerpt: ${content}`;
        })
        .join("\n\n");

      const kbContext = [
        `Knowledge base: ${selectedKnowledgeBase}`,
        `Retrieval queries: ${activeQueries.join(" | ")}`,
        `Retrieved chunks: ${retrievedChunks.length}`,
        "Use these excerpts as grounded references when generating slides.",
        "",
        lines,
      ].join("\n");

      const nextPrompt = upsertSection(
        prompt,
        KB_SECTION_START,
        KB_SECTION_END,
        kbContext.slice(0, 7000),
      );
      onPromptChange(nextPrompt);
      toast.success(
        `Retrieved ${retrievedChunks.length} knowledge chunks from ${activeQueries.length} quer${
          activeQueries.length > 1 ? "ies" : "y"
        }`,
      );
    } catch (error) {
      console.error("Failed to retrieve knowledge chunks", error);
      toast.error("Failed to retrieve knowledge chunks");
    } finally {
      setIsRetrievingKnowledge(false);
    }
  };

  const handleClearImportedContext = () => {
    const noNotebook = stripSection(prompt, NOTEBOOK_SECTION_START, NOTEBOOK_SECTION_END);
    const noKnowledge = stripSection(noNotebook, KB_SECTION_START, KB_SECTION_END);
    onPromptChange(noKnowledge);
    toast.success("Removed imported context blocks");
  };

  const toggleRecordSelection = (recordKey: string) => {
    setSelectedRecordKeys((previous) =>
      previous.includes(recordKey)
        ? previous.filter((key) => key !== recordKey)
        : [...previous, recordKey],
    );
    setActiveRecordKey(recordKey);
  };

  const handleSelectLatestRecords = () => {
    const latestKeys = notebookRecordOptions
      .slice(-Math.min(5, notebookRecordOptions.length))
      .map((item) => item.key);
    setSelectedRecordKeys(latestKeys);
    if (latestKeys.length > 0) {
      setActiveRecordKey(latestKeys[latestKeys.length - 1]);
    }
  };

  const toggleGeneratedQuery = (query: string) => {
    setSelectedGeneratedQueries((previous) =>
      previous.includes(query)
        ? previous.filter((item) => item !== query)
        : [...previous, query],
    );
  };

  return (
    <div className="mt-4 w-full rounded-xl border border-blue-200 bg-blue-50/40 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-instrument_sans text-base font-semibold text-slate-800">
            EduNote Data Sources
          </h3>
          <p className="font-instrument_sans text-sm text-slate-600">
            Import notebook records and retrieve knowledge chunks into the prompt.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          className="font-instrument_sans"
          onClick={handleClearImportedContext}
          disabled={!hasImportedNotebookContext && !hasImportedKnowledgeContext}
        >
          Clear Imported Context
        </Button>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <p className="font-instrument_sans text-sm font-semibold text-slate-700">
            Notebook Records
          </p>
          <p className="mt-1 font-instrument_sans text-xs text-slate-500">
            Import records from a notebook and append them as grounded context.
          </p>
          <div className="mt-3 space-y-3">
            <select
              className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700"
              value={selectedNotebookId}
              onChange={(event) => setSelectedNotebookId(event.target.value)}
              disabled={isLoadingOptions || notebooks.length === 0}
            >
              <option value="">Select notebook</option>
              {notebooks.map((notebook) => (
                <option key={notebook.id} value={notebook.id}>
                  {notebook.name} ({notebook.record_count ?? 0})
                </option>
              ))}
            </select>
            <div className="rounded-md border border-slate-200 bg-slate-50/60 p-2">
              <div className="mb-2 flex items-center justify-between gap-2">
                <p className="text-xs font-semibold text-slate-700">Select records to import</p>
                <div className="flex items-center gap-1">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    onClick={handleSelectLatestRecords}
                    disabled={isLoadingNotebookRecords || notebookRecordOptions.length === 0}
                  >
                    Latest 5
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 text-xs"
                    onClick={() => setSelectedRecordKeys(notebookRecordOptions.map((item) => item.key))}
                    disabled={isLoadingNotebookRecords || notebookRecordOptions.length === 0}
                  >
                    All
                  </Button>
                </div>
              </div>
              <div className="max-h-44 space-y-1 overflow-y-auto pr-1">
                {isLoadingNotebookRecords ? (
                  <div className="flex items-center text-xs text-slate-500">
                    <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                    Loading notebook records...
                  </div>
                ) : notebookRecordOptions.length === 0 ? (
                  <p className="text-xs text-slate-500">No records found in this notebook.</p>
                ) : (
                  [...notebookRecordOptions].reverse().map((item) => {
                    const checked = selectedRecordKeys.includes(item.key);
                    return (
                      <label
                        key={item.key}
                        className="flex cursor-pointer items-start gap-2 rounded border border-transparent px-1 py-1 hover:border-slate-200 hover:bg-white"
                      >
                        <input
                          type="checkbox"
                          className="mt-0.5 h-4 w-4"
                          checked={checked}
                          onChange={() => toggleRecordSelection(item.key)}
                        />
                        <button
                          type="button"
                          className="flex-1 text-left"
                          onClick={() => setActiveRecordKey(item.key)}
                        >
                          <p className="line-clamp-1 text-xs font-medium text-slate-700">
                            {normalizeText(item.record.title || `Record ${item.index + 1}`, 90)}
                          </p>
                          <p className="line-clamp-1 text-[11px] text-slate-500">
                            {normalizeText(item.record.user_query || item.record.output, 120)}
                          </p>
                        </button>
                      </label>
                    );
                  })
                )}
              </div>
              <p className="mt-2 text-[11px] text-slate-500">
                Selected: {selectedRecordKeys.length} / {notebookRecordOptions.length}
              </p>
              {activeNotebookRecord ? (
                <div className="mt-2 rounded-md border border-slate-200 bg-white p-2">
                  <p className="text-xs font-semibold text-slate-700">
                    {normalizeText(activeNotebookRecord.title || "Record preview", 120)}
                  </p>
                  <p className="mt-1 text-[11px] text-slate-600">
                    {normalizeText(
                      activeNotebookRecord.output || activeNotebookRecord.user_query,
                      260,
                    )}
                  </p>
                </div>
              ) : null}
            </div>
            <Button
              type="button"
              className="w-full font-instrument_sans"
              onClick={handleImportNotebookRecords}
              disabled={
                isLoadingOptions ||
                isImportingNotebook ||
                isLoadingNotebookRecords ||
                notebooks.length === 0 ||
                selectedRecordKeys.length === 0
              }
            >
              {isImportingNotebook ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Import Notebook Records
            </Button>
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <p className="font-instrument_sans text-sm font-semibold text-slate-700">
            Knowledge Retrieval
          </p>
          <p className="mt-1 font-instrument_sans text-xs text-slate-500">
            Search EduNote knowledge base chunks and add top results to context.
          </p>
          <div className="mt-3 space-y-3">
            <select
              className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700"
              value={selectedKnowledgeBase}
              onChange={(event) => setSelectedKnowledgeBase(event.target.value)}
              disabled={isLoadingOptions || knowledgeBases.length === 0}
            >
              <option value="">Select knowledge base</option>
              {knowledgeBases.map((kb) => (
                <option key={kb.name} value={kb.name}>
                  {kb.name}
                </option>
              ))}
            </select>
            <Input
              value={knowledgeQuery}
              onChange={(event) => setKnowledgeQuery(event.target.value)}
              placeholder="Query for retrieval (e.g., transformer architecture)"
            />
            <Button
              type="button"
              variant="outline"
              className="w-full font-instrument_sans"
              onClick={handleGenerateQueries}
              disabled={isGeneratingQueries || !prompt.trim()}
            >
              {isGeneratingQueries ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="mr-2 h-4 w-4" />
              )}
              Generate Queries From Prompt
            </Button>
            {generatedQueries.length > 0 ? (
              <div className="rounded-md border border-slate-200 bg-slate-50/60 p-2">
                <p className="mb-1 text-xs font-semibold text-slate-700">Query Agent suggestions</p>
                <div className="space-y-1">
                  {generatedQueries.map((query) => (
                    <label key={query} className="flex cursor-pointer items-start gap-2 text-xs text-slate-700">
                      <input
                        type="checkbox"
                        className="mt-0.5 h-4 w-4"
                        checked={selectedGeneratedQueries.includes(query)}
                        onChange={() => toggleGeneratedQuery(query)}
                      />
                      <span className="leading-4">{query}</span>
                    </label>
                  ))}
                </div>
                <p className="mt-2 text-[11px] text-slate-500">
                  If no suggestion is selected, manual query above will be used.
                </p>
              </div>
            ) : null}
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">
                Top chunks
              </label>
              <Input
                type="number"
                min={1}
                max={10}
                value={knowledgeChunkLimit}
                onChange={(event) =>
                  setKnowledgeChunkLimit(
                    Math.min(10, Math.max(1, Number.parseInt(event.target.value || "1", 10))),
                  )
                }
              />
            </div>
            <Button
              type="button"
              className="w-full font-instrument_sans"
              onClick={handleRetrieveKnowledge}
              disabled={isLoadingOptions || isRetrievingKnowledge || knowledgeBases.length === 0}
            >
              {isRetrievingKnowledge ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Search className="mr-2 h-4 w-4" />
              )}
              Retrieve KB Context
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
