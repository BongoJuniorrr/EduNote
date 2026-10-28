"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch, apiUrl, readApiResponse } from "@/lib/api";

type ParserConfig = {
  parser: string; fallback: string; base_url: string; model: string;
  api_key: string; mineru_tier?: string; max_pages: number; timeout_seconds: number;
};
type Preset = { id: string; label: string; parser: string; model?: string; base_url?: string; installed?: boolean | null };

export default function DocumentSettings() {
  const [config, setConfig] = useState<ParserConfig | null>(null);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [preset, setPreset] = useState("");
  const [message, setMessage] = useState("");
  const [preview, setPreview] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const activeTest = useRef<AbortController | null>(null);
  const inputClass = "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100";

  useEffect(() => {
    apiFetch(apiUrl("/api/v1/config/documents")).then(async response => {
      const data = await readApiResponse(response);
      setConfig(data.config); setPresets(data.presets);
      const match = data.presets.find((x: Preset) => x.parser === data.config.parser && (!x.model || x.model === data.config.model));
      setPreset(match?.id || "auto");
    }).catch(e => { setError(true); setMessage(e.message); });
  }, []);
  useEffect(() => () => activeTest.current?.abort(), []);

  const save = async () => {
    const response = await apiFetch(apiUrl("/api/v1/config/documents"), {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config),
    });
    const data = await readApiResponse(response);
    setConfig(data.config);
  };

  const submit = async (test: boolean) => {
    setBusy(true); setMessage(""); setError(false); setPreview("");
    const controller = new AbortController();
    activeTest.current = controller;
    try {
      await save();
      if (test && file) {
        const body = new FormData(); body.append("file", file);
        const response = await apiFetch(apiUrl("/api/v1/config/documents/test?background=true"), { method: "POST", body, signal: controller.signal });
        const started = await readApiResponse(response);
        const deadline = Date.now() + ((config?.timeout_seconds || 300) + 600) * 1000;
        let data;
        while (Date.now() < deadline) {
          const state = await readApiResponse(await apiFetch(apiUrl(`/api/v1/config/documents/tests/${encodeURIComponent(started.test_id)}`), { cache: "no-store", signal: controller.signal }));
          if (state.status === "completed") { data = state.result; break; }
          if (["failed", "cancelled"].includes(state.status)) throw new Error(state.error || "Document test was cancelled");
          setMessage(state.status === "queued" ? "Document test queued. Waiting for the parser worker…" : "Extracting document… First use may download parser models. You can keep using other features.");
          await new Promise(resolve => setTimeout(resolve, 1000));
        }
        if (!data) throw new Error("The document test is still waiting or processing. Check worker availability before submitting another test.");
        setMessage(`Extracted ${data.blocks} blocks with ${data.parser}. ${(data.warnings || []).join("; ")}`);
        setPreview(data.preview);
      } else setMessage("Document settings saved. Changes apply to new ingestion and reindexing.");
    } catch (e) { if (!controller.signal.aborted) { setError(true); setMessage(e instanceof Error ? e.message : "Request failed"); } }
    finally { if (!controller.signal.aborted) setBusy(false); }
  };

  if (!config) return <div className="p-6">{message || "Loading document settings..."}</div>;
  const endpoint = ["vision", "mineru_http"].includes(config.parser);
  return <section className="p-6 space-y-5">
    <div><h2 className="text-xl font-semibold">Document processing</h2>
      <p className="mt-2 text-sm text-slate-500">Select extraction independently from RAG retrieval. Auto stays local; cloud services are used only when selected. Install optional packages and serve vision models before testing.</p></div>
    <label className="block">Pipeline preset
      <select aria-label="Document pipeline" className={inputClass} value={preset} onChange={event => {
        const selected = presets.find(x => x.id === event.target.value)!;
        setPreset(selected.id);
        setConfig({ ...config, parser: selected.parser, base_url: selected.base_url || "", model: selected.model || "", api_key: "", fallback: "none" });
      }}>{presets.map(x => <option key={x.id} value={x.id}>{x.label}{x.installed === false ? " · package not installed" : ""}</option>)}</select>
    </label>
    {["mineru", "mineru_http"].includes(config.parser) && <label className="block">MinerU quality tier
      <select aria-label="MinerU quality tier" className={inputClass} value={config.mineru_tier || "basic"} onChange={e => setConfig({ ...config, mineru_tier: e.target.value })}>
        <option value="flash">Flash · native digital text (no OCR)</option><option value="basic">Basic · local ONNX OCR, tables and formulas</option><option value="standard">Standard · layout and document understanding</option><option value="advanced">Advanced · larger vision model</option>
      </select>
    </label>}
    {config.parser === "mineru" && ["standard", "advanced"].includes(config.mineru_tier || "basic") && <p className="text-sm text-amber-600 dark:text-amber-400">This tier loads an additional vision model. First startup may take several minutes. Increase the extraction timeout if needed; Basic uses the lighter ONNX pipeline.</p>}
    {endpoint && <>
      <label className="block">Parser endpoint
        <input aria-label="Parser endpoint" type="url" autoComplete="off" className={inputClass} value={config.base_url} onChange={e => setConfig({ ...config, base_url: e.target.value })} />
      </label>
      <p className="text-sm text-slate-500">Use host.docker.internal to reach a server on the Docker host. The model name must match the name served by that endpoint.</p>
    </>}
    {config.parser === "vision" && <label className="block">Served vision model
      <input aria-label="Served vision model" className={inputClass} value={config.model} onChange={e => setConfig({ ...config, model: e.target.value })} />
    </label>}
    {(endpoint || config.parser === "llamaparse") && <label className="block">Parser API key (optional for local servers)
      <input aria-label="Parser API key" type="password" autoComplete="new-password" className={inputClass} value={config.api_key} onChange={e => setConfig({ ...config, api_key: e.target.value })} />
    </label>}
    <div className="grid gap-4 sm:grid-cols-3">
      <label>Fallback<select aria-label="Parser fallback" className={inputClass} value={config.fallback} onChange={e => setConfig({ ...config, fallback: e.target.value })}>
        <option value="none">Stop and report an error</option><option value="pymupdf">PyMuPDF (digital text only)</option>
      </select></label>
      <label>Maximum pages<input aria-label="Maximum document pages" type="number" min={1} max={2000} className={inputClass} value={config.max_pages} onChange={e => setConfig({ ...config, max_pages: Number(e.target.value) })} /></label>
      <label>Timeout (seconds)<input aria-label="Parser timeout" type="number" min={5} max={1800} className={inputClass} value={config.timeout_seconds} onChange={e => setConfig({ ...config, timeout_seconds: Number(e.target.value) })} /></label>
    </div>
    <p className="text-sm text-slate-500">Native RAG-Anything/Docling pipelines retain their own parser. These settings control the LlamaIndex and VGU Course document ingestion paths. Existing indexes need reindexing to use another parser or embedding model.</p>
    <button disabled={busy} onClick={() => submit(false)} className="rounded-lg bg-blue-600 px-4 py-2 text-white disabled:opacity-50">{busy ? "Processing..." : "Save document settings"}</button>
    <div className="border-t border-slate-200 pt-4 dark:border-slate-700 space-y-3">
      <label className="block">Test with a document (20 MiB maximum)
        <input aria-label="Preview document" type="file" accept=".pdf,.docx,.pptx,.png,.jpg,.jpeg,.txt,.md" onChange={e => setFile(e.target.files?.[0] || null)} className="block mt-2 text-sm" />
      </label>
      <button disabled={!file || busy} onClick={() => submit(true)} className="rounded-lg border border-blue-500 px-4 py-2 disabled:opacity-50">Save and test extraction</button>
    </div>
    {message && <p role={error ? "alert" : "status"} className={error ? "text-red-500" : "text-green-600"}>{message}</p>}
    {preview && <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-100 p-4 text-sm dark:bg-slate-900">{preview}</pre>}
  </section>;
}
