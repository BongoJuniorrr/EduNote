export type WorkflowType =
  | "slide_deck"
  | "exam_blueprint"
  | "lesson_plan"
  | "learning_outcome_mapper"
  | "rubric_builder"
  | "misconception_detector"
  | "adaptive_quiz_coach"
  | "curriculum_alignment"
  | "content_safety_fact_check";

export type RAGMode = "hybrid" | "local" | "global" | "naive";
export type SearchMode = "quick" | "balanced" | "deep";

export type SettingsValue =
  | string
  | number
  | boolean
  | string[]
  | number[]
  | boolean[]
  | null;

export interface SettingsTemplate {
  id: string;
  name: string;
  description: string;
  settings: Record<string, SettingsValue>;
}

export interface WorkflowConfig {
  id: WorkflowType;
  name: string;
  description: string;
  templates: SettingsTemplate[];
}

export interface WorkflowCatalogResponse {
  workflows: WorkflowConfig[];
}

export interface ContextEnrichmentConfig {
  enable_rag: boolean;
  kb_name: string;
  rag_mode: RAGMode;
  enable_web_search: boolean;
  search_mode: SearchMode;
  search_provider: string;
}

export interface EduStudioRunRequest {
  workflow: WorkflowType;
  title: string;
  language: "vi" | "en";
  source_text: string;
  instructions: string;
  settings: Record<string, SettingsValue>;
  settings_template: string;
  context_enrichment: ContextEnrichmentConfig;
  model_config_id: string;
  materials: Array<{
    title: string;
    content: string;
    metadata: Record<string, unknown>;
  }>;
}

export interface DeckTheme {
  palette: {
    background: string;
    foreground: string;
    accent: string;
    muted: string;
  };
  typography: {
    font_family: string;
    title_scale: string;
    body_scale: string;
  };
  visual_style: string;
  ratio: string;
}

export interface SlideData {
  title: string;
  objective: string;
  key_points: string[];
  activity: string;
  speaker_notes: string;
  layout_hint: "title" | "bullets" | "comparison" | "timeline" | "equation" | "summary";
  visual_hint: string;
  visual_prompt?: string;
}

export interface SlideDeckData {
  deck_theme: DeckTheme;
  slides: SlideData[];
  design_guidelines: string[];
  assessment_checkpoints: string[];
  [key: string]: unknown;
}

export interface QualityCheck {
  name: string;
  status: "pass" | "warn" | "info" | "error" | "fail" | string;
  detail: string;
}

export interface ArtifactMeta {
  file_name: string;
  size_bytes: number;
  content_type: string;
  uploaded_at: string;
  url: string;
}

export interface EduStudioResult {
  workflow: WorkflowType;
  title: string;
  summary: string;
  deliverable_markdown: string;
  structured_data: Record<string, unknown>;
  quality_checks: QualityCheck[];
  next_actions: string[];
  metadata?: {
    model?: string;
    provider?: string;
    generated_at?: string;
    language?: string;
  };
}

export interface ParsedMaterialSummary {
  filename: string;
  content_type: string;
  metadata: Record<string, unknown>;
  warnings: string[];
  content_length: number;
}

export interface EduStudioRunResponse {
  success: boolean;
  workflow: WorkflowType;
  run_id: string;
  artifact_base_url: string;
  artifacts: ArtifactMeta[];
  context_enrichment?: Record<string, unknown>;
  result: EduStudioResult;
  parsed_materials: ParsedMaterialSummary[];
  warnings: string[];
}

export interface ArtifactUploadResponse {
  success: boolean;
  run_id: string;
  workflow?: string;
  artifact_base_url: string;
  artifacts: ArtifactMeta[];
}

export interface RunMetadataResponse {
  success: boolean;
  run_id: string;
  workflow: string;
  created_at: string;
  updated_at: string;
  artifact_base_url: string;
  artifacts: ArtifactMeta[];
}
