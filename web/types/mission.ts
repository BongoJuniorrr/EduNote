export type MissionPreset =
  | "learn_topic"
  | "capstone_prep"
  | "defense_prep"
  | "custom";

export type MissionRunStatus =
  | "draft"
  | "awaiting_approval"
  | "approved"
  | "running"
  | "completed"
  | "failed";

export type MissionStepType =
  | "knowledge_map"
  | "idea_board"
  | "research_brief"
  | "final_dossier"
  | "review";

export interface MissionBrief {
  working_title: string;
  objective: string;
  rationale: string;
  deliverables: string[];
  success_criteria: string[];
  constraints: string[];
  assumptions: string[];
  required_resources: string[];
  execution_notes: string[];
  key_questions: string[];
}

export interface MissionStep {
  step_id: string;
  title: string;
  step_type: MissionStepType;
  rationale: string;
  depends_on: string[];
  outputs: string[];
  approval_required: boolean;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  summary: string;
  artifact_ids: string[];
  metadata: Record<string, any>;
}

export interface MissionArtifact {
  artifact_id: string;
  kind: string;
  title: string;
  summary: string;
  source_step_id?: string | null;
  file_name: string;
  file_path: string;
  url: string;
  content_type: string;
  created_at: string;
  preview: string;
  metadata: Record<string, any>;
}

export interface MissionReview {
  status: "pass" | "revise";
  score: number;
  strengths: string[];
  risks: string[];
  missing_items: string[];
  recommended_changes: string[];
  final_recommendation: string;
}

export interface MissionRun {
  run_id: string;
  title: string;
  status: MissionRunStatus;
  preset: MissionPreset;
  goal: string;
  primary_kb_name?: string | null;
  notebook_ids: string[];
  desired_outputs: string[];
  constraints: string;
  success_criteria: string;
  research_depth: "quick" | "medium" | "deep";
  brief?: MissionBrief | null;
  plan: MissionStep[];
  artifacts: MissionArtifact[];
  review?: MissionReview | null;
  result_summary: string;
  context_summary: Record<string, any>;
  created_at: string;
  updated_at: string;
  approved_at?: string | null;
  completed_at?: string | null;
  error?: string | null;
  events: Array<Record<string, any>>;
}

export interface MissionTemplate {
  id: MissionPreset;
  label: string;
  description: string;
  default_outputs: string[];
  recommended_when: string[];
}

export interface MissionRunSummary {
  run_id: string;
  title: string;
  status: MissionRunStatus;
  preset: MissionPreset;
  goal: string;
  created_at: string;
  updated_at: string;
  artifact_count: number;
  step_count: number;
  review_status?: "pass" | "revise" | null;
}

export interface MissionEvent {
  type: string;
  timestamp?: string;
  [key: string]: any;
}
