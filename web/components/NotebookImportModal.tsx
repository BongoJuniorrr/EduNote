"use client";
import { apiFetch } from '@/lib/api';

import { useState, useEffect } from "react";
import {
  X,
  BookOpen,
  ChevronRight,
  ChevronDown,
  Loader2,
  Check,
  Calendar,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { apiUrl } from "@/lib/api";

interface Notebook {
  id: string;
  name: string;
  description: string;
  record_count: number;
  color: string;
  updated_at?: string;
}

interface NotebookRecord {
  id: string;
  title: string;
  user_query: string;
  output: string;
  type: string;
  created_at?: string | number;
  metadata?: Record<string, unknown>;
  source_notebook_id?: string;
}

interface SelectedNotebookRecord extends NotebookRecord {
  _selectionKey: string;
  _sourceNotebookId: string;
}

interface NotebookImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  onImport: (content: string, records: NotebookRecord[]) => void;
  title?: string;
}

export default function NotebookImportModal({
  isOpen,
  onClose,
  onImport,
  title,
}: NotebookImportModalProps) {
  const { t } = useTranslation();
  const dialogTitle = title ?? t("Import from Notebooks");
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedNotebooks, setExpandedNotebooks] = useState<Set<string>>(
    new Set(),
  );
  const [notebookRecords, setNotebookRecords] = useState<
    Map<string, NotebookRecord[]>
  >(new Map());
  const [loadingRecords, setLoadingRecords] = useState<Set<string>>(new Set());
  const [selectedRecords, setSelectedRecords] = useState<Set<string>>(
    new Set(),
  ); // Scoped keys: {notebookId}:{recordId}
  const [selectedRecordsData, setSelectedRecordsData] = useState<
    SelectedNotebookRecord[]
  >([]);

  const [previousOpen, setPreviousOpen] = useState(isOpen);
  if (previousOpen !== isOpen) {
    setPreviousOpen(isOpen); setSelectedRecords(new Set()); setSelectedRecordsData([]); setExpandedNotebooks(new Set()); setLoading(isOpen);
  }

  function fetchNotebooks() {
    return apiFetch(apiUrl("/api/v1/notebook/list"))
      .then(response => { if (!response.ok) throw new Error(`Notebooks HTTP ${response.status}`); return response.json(); })
      .then(data => setNotebooks((data.notebooks || []).filter((nb: Notebook) => nb.record_count > 0)))
      .catch(error => console.error("Could not load notebooks:", error))
      .finally(() => setLoading(false));
  }

  useEffect(() => { if (isOpen) void fetchNotebooks(); }, [isOpen]);

  const fetchRecords = async (notebookId: string) => {
    if (notebookRecords.has(notebookId)) return;

    setLoadingRecords((prev) => new Set(prev).add(notebookId));
    try {
      const res = await apiFetch(apiUrl(`/api/v1/notebook/${notebookId}`));
      if (res.ok) {
        const data = await res.json();
        setNotebookRecords((prev) =>
          new Map(prev).set(notebookId, data.records || []),
        );
      }
    } catch (error) {
      console.error(
        `Failed to fetch records for notebook ${notebookId}:`,
        error,
      );
    } finally {
      setLoadingRecords((prev) => {
        const next = new Set(prev);
        next.delete(notebookId);
        return next;
      });
    }
  };

  const toggleNotebook = (notebookId: string) => {
    setExpandedNotebooks((prev) => {
      const next = new Set(prev);
      if (next.has(notebookId)) {
        next.delete(notebookId);
      } else {
        next.add(notebookId);
        fetchRecords(notebookId);
      }
      return next;
    });
  };

  const buildSelectionKey = (notebookId: string, recordId: string) =>
    `${notebookId}:${recordId}`;

  const normalizeTimestamp = (createdAt?: string | number): number => {
    if (createdAt === undefined || createdAt === null) return 0;
    if (typeof createdAt === "number") {
      return createdAt < 10_000_000_000 ? createdAt * 1000 : createdAt;
    }
    const parsed = Number(createdAt);
    if (!Number.isNaN(parsed)) {
      return parsed < 10_000_000_000 ? parsed * 1000 : parsed;
    }
    return 0;
  };

  const coerceText = (value: unknown): string => {
    if (typeof value === "string") return value.trim();
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    if (Array.isArray(value)) {
      return value
        .map((item) => coerceText(item))
        .filter(Boolean)
        .join("\n")
        .trim();
    }
    if (value && typeof value === "object") {
      const obj = value as Record<string, unknown>;
      const ordered = [
        obj.markdown,
        obj.normalized_text,
        obj.text,
        obj.content,
        obj.summary,
        obj.description,
        obj.notes,
      ];
      for (const candidate of ordered) {
        const asText = coerceText(candidate);
        if (asText) return asText;
      }
      try {
        return JSON.stringify(obj, null, 2);
      } catch {
        return "";
      }
    }
    return "";
  };

  const normalizeRecord = (record: SelectedNotebookRecord): NotebookRecord => {
    const metadata =
      record.metadata && typeof record.metadata === "object"
        ? (record.metadata as Record<string, unknown>)
        : {};
    const output =
      coerceText(record.output) ||
      coerceText(metadata.markdown) ||
      coerceText(metadata.normalized_text) ||
      coerceText(metadata.text) ||
      coerceText(metadata.notes) ||
      coerceText(metadata.content);
    return {
      id: record.id,
      title: record.title,
      user_query: record.user_query,
      output,
      type: record.type,
      created_at: record.created_at,
      metadata,
      source_notebook_id: record._sourceNotebookId,
    };
  };

  const toImportChunk = (record: NotebookRecord): string => {
    const title = coerceText(record.title) || "Untitled";
    const typeLabel = coerceText(record.type).toUpperCase() || "RECORD";
    const query = coerceText(record.user_query);
    const output = coerceText(record.output);
    const lines = [`## ${title}`, `Type: ${typeLabel}`];
    if (query) {
      lines.push("", `Prompt: ${query}`);
    }
    if (output) {
      lines.push("", output);
    } else {
      lines.push("", "(No textual output found in this record.)");
    }
    return lines.join("\n");
  };

  const toggleRecordSelection = (record: NotebookRecord, notebookId: string) => {
    const selectionKey = buildSelectionKey(notebookId, record.id);
    setSelectedRecords((prev) => {
      const next = new Set(prev);
      if (next.has(selectionKey)) {
        next.delete(selectionKey);
        setSelectedRecordsData((current) =>
          current.filter((r) => r._selectionKey !== selectionKey),
        );
      } else {
        next.add(selectionKey);
        setSelectedRecordsData((current) => [
          ...current,
          {
            ...record,
            _selectionKey: selectionKey,
            _sourceNotebookId: notebookId,
          },
        ]);
      }
      return next;
    });
  };

  const handleImport = () => {
    const normalizedRecords = selectedRecordsData
      .map((record) => normalizeRecord(record))
      .sort(
        (a, b) =>
          normalizeTimestamp(a.created_at) - normalizeTimestamp(b.created_at),
      );
    const mergedContent = normalizedRecords
      .map((record) => toImportChunk(record))
      .join("\n\n---\n\n");
    onImport(mergedContent, normalizedRecords);
    onClose();
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="w-[800px] h-[600px] bg-white rounded-2xl shadow-2xl flex flex-col overflow-hidden animate-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="p-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
          <div className="flex items-center gap-2">
            <div className="p-2 bg-blue-100 rounded-lg">
              <BookOpen className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <h2 className="font-bold text-slate-900">{dialogTitle}</h2>
              <p className="text-xs text-slate-500">
                {t("Select content from your notebooks to import")}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-slate-200 rounded-full transition-colors"
          >
            <X className="w-5 h-5 text-slate-500" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 flex overflow-hidden">
          {/* Notebooks List */}
          <div className="w-1/3 border-r border-slate-100 overflow-y-auto bg-slate-50/30 p-2 space-y-2">
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
              </div>
            ) : notebooks.length === 0 ? (
              <div className="text-center py-8 text-slate-400 text-sm">
                {t("No notebooks found")}
              </div>
            ) : (
              notebooks.map((nb) => (
                <div
                  key={nb.id}
                  onClick={() => toggleNotebook(nb.id)}
                  className={`p-3 rounded-xl cursor-pointer transition-all border ${
                    expandedNotebooks.has(nb.id)
                      ? "bg-white border-blue-200 shadow-sm"
                      : "hover:bg-white border-transparent hover:border-slate-200"
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    {expandedNotebooks.has(nb.id) ? (
                      <ChevronDown className="w-4 h-4 text-slate-400" />
                    ) : (
                      <ChevronRight className="w-4 h-4 text-slate-400" />
                    )}
                    <div
                      className="w-3 h-3 rounded-full"
                      style={{ backgroundColor: nb.color || "#94a3b8" }}
                    />
                    <span className="font-medium text-sm text-slate-700 truncate flex-1">
                      {nb.name}
                    </span>
                  </div>
                  <div className="pl-6 text-xs text-slate-400 flex justify-between">
                    <span>{nb.record_count} records</span>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Records List */}
          <div className="flex-1 overflow-y-auto p-4 bg-white">
            {expandedNotebooks.size === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-slate-400">
                <BookOpen className="w-12 h-12 mb-3 opacity-20" />
                <p>{t("Select a notebook to view records")}</p>
              </div>
            ) : (
              <div className="space-y-4">
                {Array.from(expandedNotebooks).map((nbId) => {
                  const nb = notebooks.find((n) => n.id === nbId);
                  const records = notebookRecords.get(nbId);
                  const isLoading = loadingRecords.has(nbId);

                  if (!nb) return null;

                  return (
                    <div
                      key={nbId}
                      className="animate-in fade-in slide-in-from-bottom-2"
                    >
                      <h3 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2 pl-1 sticky top-0 bg-white py-2 z-10 flex items-center gap-2">
                        <div
                          className="w-2 h-2 rounded-full"
                          style={{ backgroundColor: nb.color }}
                        />
                        {nb.name}
                      </h3>

                      {isLoading ? (
                        <div className="py-4 flex justify-center">
                          <Loader2 className="w-5 h-5 animate-spin text-slate-300" />
                        </div>
                      ) : !records || records.length === 0 ? (
                        <div className="py-4 text-center text-xs text-slate-400 italic">
                          {t("No records")}
                        </div>
                      ) : (
                        <div className="grid gap-2">
                          {records.map((record) => {
                            const selectionKey = buildSelectionKey(
                              nbId,
                              record.id,
                            );
                            const isSelected = selectedRecords.has(selectionKey);
                            return (
                              <div
                                key={`${nbId}:${record.id}`}
                                onClick={() => toggleRecordSelection(record, nbId)}
                                className={`p-3 rounded-xl border cursor-pointer transition-all group ${
                                  isSelected
                                    ? "bg-blue-50 border-blue-200 ring-1 ring-blue-200"
                                    : "bg-white border-slate-200 hover:border-blue-200 hover:shadow-sm"
                                }`}
                              >
                                <div className="flex items-start gap-3">
                                  <div
                                    className={`w-5 h-5 rounded border flex items-center justify-center shrink-0 mt-0.5 transition-colors ${
                                      isSelected
                                        ? "bg-blue-500 border-blue-500 text-white"
                                        : "border-slate-300 group-hover:border-blue-300"
                                    }`}
                                  >
                                    {isSelected && (
                                      <Check className="w-3.5 h-3.5" />
                                    )}
                                  </div>
                                  <div className="flex-1 min-w-0">
                                    <h4 className="text-sm font-medium text-slate-900 truncate mb-0.5">
                                      {record.title}
                                    </h4>
                                    <p className="text-xs text-slate-500 line-clamp-2">
                                      {record.output}
                                    </p>
                                    <div className="mt-2 flex items-center gap-2">
                                      <span className="px-1.5 py-0.5 bg-slate-100 text-slate-500 text-[10px] rounded font-medium uppercase">
                                        {record.type}
                                      </span>
                                      {record.created_at && (
                                        <span className="flex items-center gap-1 text-[10px] text-slate-400">
                                          <Calendar className="w-3 h-3" />
                                          {new Date(
                                            normalizeTimestamp(record.created_at),
                                          ).toLocaleDateString()}
                                        </span>
                                      )}
                                    </div>
                                  </div>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-slate-100 bg-slate-50 flex justify-between items-center">
          <div className="text-sm text-slate-500">
            {t("Selected {n} items").replace(
              "{n}",
              String(selectedRecords.size),
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-200 rounded-lg transition-colors"
            >
              {t("Cancel")}
            </button>
            <button
              onClick={handleImport}
              disabled={selectedRecords.size === 0}
              className="px-4 py-2 text-sm font-bold text-white bg-blue-600 hover:bg-blue-700 rounded-lg shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              <Check className="w-4 h-4" />
              {t("Import Selected")}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
