from pathlib import Path

from src.agents.mission.schemas import (
    MissionBrief,
    MissionPlanRequest,
    MissionReview,
    MissionStep,
)
from src.agents.mission.state_store import MissionStateStore


def _sample_brief() -> MissionBrief:
    return MissionBrief(
        working_title="Mission Test",
        objective="Build a grounded mission dossier.",
        rationale="Test mission persistence.",
        deliverables=["research_brief", "final_dossier"],
        success_criteria=["Produces a dossier"],
        constraints=["Stay grounded"],
        assumptions=["Test environment"],
        required_resources=["KB"],
        execution_notes=["Keep short"],
        key_questions=["What evidence is needed?"],
    )


def _sample_plan() -> list[MissionStep]:
    return [
        MissionStep(
            step_id="step_1",
            title="Research",
            step_type="research_brief",
            rationale="Gather evidence",
            outputs=["research_brief"],
        ),
        MissionStep(
            step_id="step_2",
            title="Review",
            step_type="review",
            rationale="Quality gate",
            depends_on=["step_1"],
            outputs=["review"],
        ),
    ]


def test_state_store_creates_run_and_artifacts(tmp_path: Path):
    store = MissionStateStore(base_dir=tmp_path / "mission")
    request = MissionPlanRequest(
        goal="Prepare a mission dossier",
        preset="custom",
        desired_outputs=["research_brief", "final_dossier"],
        research_depth="medium",
    )

    run = store.create_run(
        request,
        _sample_brief(),
        _sample_plan(),
        title="Mission Test",
        status="awaiting_approval",
        context_summary={"selected_primary_kb": "ai_textbook"},
    )

    assert run.run_id.startswith("mission_")
    assert run.status == "awaiting_approval"
    assert len(run.artifacts) >= 2
    assert (tmp_path / "mission" / run.run_id / "run.json").exists()
    assert (
        tmp_path / "mission" / run.run_id / "artifacts" / "mission_brief.json"
    ).exists()


def test_state_store_updates_steps_events_review_and_artifacts(tmp_path: Path):
    store = MissionStateStore(base_dir=tmp_path / "mission")
    request = MissionPlanRequest(
        goal="Prepare a mission dossier",
        preset="custom",
        desired_outputs=["research_brief", "final_dossier"],
        research_depth="medium",
    )
    run = store.create_run(
        request,
        _sample_brief(),
        _sample_plan(),
        title="Mission Test",
        status="approved",
        context_summary={},
    )

    store.append_event(run.run_id, "run_started", {"step_count": 2})
    store.update_step(run.run_id, "step_1", status="completed", summary="done")
    artifact = store.save_text_artifact(
        run.run_id,
        kind="final_dossier",
        title="Final Dossier",
        content="# Final Dossier\n\nBody",
        source_step_id="step_2",
        file_name="final_dossier.md",
        summary="Compiled dossier",
    )
    review = MissionReview(
        status="pass",
        score=0.91,
        strengths=["Grounded"],
        risks=[],
        missing_items=[],
        recommended_changes=[],
        final_recommendation="Ready",
    )
    store.set_review(run.run_id, review)
    updated = store.set_status(run.run_id, "completed", result_summary="Ready")

    assert artifact.url.endswith("/final_dossier.md")
    assert updated.status == "completed"
    assert updated.review is not None
    assert updated.review.status == "pass"
    assert updated.result_summary == "Ready"
    assert any(event["type"] == "run_started" for event in updated.events)
