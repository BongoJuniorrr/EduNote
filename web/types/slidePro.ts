import { NotebookRecordType } from "./notebook";

export type SlideElementType =
  | "text"
  | "bullets"
  | "shape"
  | "icon"
  | "image"
  | "chart"
  | "equation"
  | "table";

export interface SlideElementBox {
  x: number;
  y: number;
  w: number;
  h: number;
  rot: number;
}

export interface SlideElementStyle extends Record<string, string | number | boolean | undefined> {
  fillOpacity?: number;
  textFit?: "none" | "shrink";
}

export interface SlideElement {
  id: string;
  type: SlideElementType;
  box: SlideElementBox;
  style: SlideElementStyle;
  content?: string | string[];
  data?: Record<string, unknown>;
  src?: string;
  asset_hint?: string;
  evidence_refs?: string[];
}

export interface SlideCritic {
  density: number;
  readability: number;
  issues: string[];
}

export interface SlideProSlide {
  id: string;
  title: string;
  notes: string;
  elements: SlideElement[];
  critic: SlideCritic;
  citations?: SlideProEvidenceRef[];
  citation_footer?: string[];
}

export interface SlideProTheme {
  palette: {
    background: string;
    foreground: string;
    accent: string;
    muted: string;
  };
  fonts: {
    title: string;
    body: string;
  };
}

export interface SlideProDeck {
  version: "1.0" | "1.1";
  deck_id: string;
  meta: {
    title: string;
    language: "vi" | "en";
    template_id: string;
    template_pack?: string;
    render_contract?: "pptx_first_v1";
    learning_goals?: string[];
  };
  size: {
    width: number;
    height: number;
  };
  theme: SlideProTheme;
  slides: SlideProSlide[];
}

export interface SlideProTemplate {
  id: string;
  name: string;
  description: string;
  theme: SlideProTheme;
}

export interface SlideProEvidenceRef {
  id: string;
  source_type: "web" | "kb";
  title: string;
  short_ref: string;
  url?: string;
  source?: string;
  snippet?: string;
  kb_name?: string;
  doc_name?: string;
  page_start?: number;
  page_end?: number;
  section_path?: string;
  chunk_id?: string;
}

export type SlideProResearchEffort = "fast" | "medium" | "high";

export interface SlideProKnowledgeBaseOption {
  name: string;
  is_default: boolean;
  rag_provider: string;
  search_mode: string;
  retrieval_profile: string;
}

export interface SlideProSearchProviderOption {
  id: string;
  name: string;
  display_name?: string;
  description?: string;
  supports_answer?: boolean;
}

export interface SlideProResearchOptionsResponse {
  knowledge_bases: SlideProKnowledgeBaseOption[];
  default_kb_names: string[];
  search: {
    default_provider: string;
    providers: SlideProSearchProviderOption[];
    default_effort: SlideProResearchEffort;
    efforts: Array<{
      id: SlideProResearchEffort;
      label: string;
      description: string;
    }>;
  };
}

export interface SlideProGenerateRequest {
  title: string;
  language: "vi" | "en";
  source_text: string;
  source_records?: Array<Record<string, unknown>>;
  instructions: string;
  settings: {
    slide_count: number;
    template_id: string;
    style?: string;
    enable_kb_research?: boolean;
    enable_web_search?: boolean;
    kb_names?: string[];
    kb_name?: string;
    search_provider?: string;
    search_effort?: SlideProResearchEffort;
    max_instruction_loops?: number;
    [key: string]: unknown;
  };
}

export interface SlideProGenerateResponse {
  success: boolean;
  run_id: string;
  artifact_base_url: string;
  artifacts: Array<{
    file_name: string;
    size_bytes: number;
    content_type: string;
    uploaded_at: string;
    url: string;
  }>;
  deck_json: SlideProDeck;
  plan: {
    learning_goals: string[];
    slides: Array<{
      title: string;
      objective: string;
      key_points: string[];
      speaker_notes?: string;
      asset_focus?: string;
    }>;
    source: "llm" | "fallback";
  };
  critic_issues: Array<{ slide_id: string; issues: string[] }>;
  suggested_patches: Array<Record<string, unknown>>;
  quality_checks: Array<{ name: string; status: string; detail: string }>;
  warnings: string[];
  research_trace?: {
    enabled_kb: boolean;
    enabled_search: boolean;
    queries?: string[];
    kb_runs: Array<{
      kb_name: string;
      query?: string;
      provider?: string;
      mode?: string;
      retrieval_profile?: string;
      latency_ms?: number;
      citation_count?: number;
      warning?: string;
    }>;
    web_run?: {
      provider?: string;
      effort?: SlideProResearchEffort;
      query_count?: number;
      latency_ms?: number;
      citation_count?: number;
      warning?: string;
    };
    latencies_ms?: {
      web?: number;
      kb_total?: number;
      total?: number;
    };
    warnings?: string[];
  };
  evidence_catalog?: SlideProEvidenceRef[];
  slide_evidence?: Record<string, SlideProEvidenceRef[]>;
  instruction_report?: {
    unresolved_major: Array<{ slide_id: string; reasons: string[] }>;
    unresolved_minor: Array<{ slide_id: string; reasons: string[] }>;
    attempts_by_slide: Record<string, number>;
  };
}

export interface SlideProCriticResponse {
  deck_json: SlideProDeck;
  issues: Array<{ slide_id: string; issues: string[] }>;
  suggested_patches: Array<Record<string, unknown>>;
}

export const SLIDE_PRO_NOTEBOOK_TYPE: NotebookRecordType = "slide_pro";
