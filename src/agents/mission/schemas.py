from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


MissionPreset = Literal["learn_topic", "capstone_prep", "defense_prep", "custom"]
MissionRunStatus = Literal[
    "draft",
    "awaiting_approval",
    "approved",
    "running",
    "completed",
    "failed",
]
MissionStepType = Literal[
    "knowledge_map",
    "idea_board",
    "research_brief",
    "final_dossier",
    "review",
]
MissionStepStatus = Literal["pending", "running", "completed", "failed", "skipped"]
MissionReviewStatus = Literal["pass", "revise"]


class MissionPlanRequest(BaseModel):
    goal: str = Field(..., min_length=5)
    preset: MissionPreset = "custom"
    primary_kb_name: str | None = None
    notebook_ids: list[str] = Field(default_factory=list)
    desired_outputs: list[str] = Field(default_factory=list)
    constraints: str = ""
    success_criteria: str = ""
    research_depth: Literal["quick", "medium", "deep"] = "medium"
    auto_approve_plan: bool = False


class MissionBrief(BaseModel):
    working_title: str
    objective: str
    rationale: str = ""
    deliverables: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    required_resources: list[str] = Field(default_factory=list)
    execution_notes: list[str] = Field(default_factory=list)
    key_questions: list[str] = Field(default_factory=list)


class MissionStep(BaseModel):
    step_id: str
    title: str
    step_type: MissionStepType
    rationale: str = ""
    depends_on: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    approval_required: bool = False
    status: MissionStepStatus = "pending"
    summary: str = ""
    artifact_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MissionArtifact(BaseModel):
    artifact_id: str
    kind: str
    title: str
    summary: str = ""
    source_step_id: str | None = None
    file_name: str = ""
    file_path: str = ""
    url: str = ""
    content_type: str = "text/markdown"
    created_at: str
    preview: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class MissionReview(BaseModel):
    status: MissionReviewStatus = "revise"
    score: float = 0.0
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)
    recommended_changes: list[str] = Field(default_factory=list)
    final_recommendation: str = ""


class MissionRun(BaseModel):
    run_id: str
    title: str
    status: MissionRunStatus
    preset: MissionPreset
    goal: str
    primary_kb_name: str | None = None
    notebook_ids: list[str] = Field(default_factory=list)
    desired_outputs: list[str] = Field(default_factory=list)
    constraints: str = ""
    success_criteria: str = ""
    research_depth: Literal["quick", "medium", "deep"] = "medium"
    brief: MissionBrief | None = None
    plan: list[MissionStep] = Field(default_factory=list)
    artifacts: list[MissionArtifact] = Field(default_factory=list)
    review: MissionReview | None = None
    result_summary: str = ""
    context_summary: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    approved_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)


class MissionTemplate(BaseModel):
    id: MissionPreset
    label: str
    description: str
    default_outputs: list[str] = Field(default_factory=list)
    recommended_when: list[str] = Field(default_factory=list)
