import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("starlette")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agents.mission.schemas import MissionBrief, MissionReview, MissionRun, MissionStep, MissionTemplate
from src.api.routers import mission as mission_router


def _sample_run(status: str = "awaiting_approval") -> MissionRun:
    return MissionRun(
        run_id="mission_test_001",
        title="Mission Test",
        status=status,  # type: ignore[arg-type]
        preset="custom",
        goal="Prepare a mission dossier",
        notebook_ids=[],
        desired_outputs=["research_brief", "final_dossier"],
        constraints="",
        success_criteria="",
        research_depth="medium",
        brief=MissionBrief(
            working_title="Mission Test",
            objective="Prepare a mission dossier",
            rationale="Test router flow",
            deliverables=["research_brief", "final_dossier"],
            success_criteria=["Deliver dossier"],
            constraints=[],
            assumptions=[],
            required_resources=[],
            execution_notes=[],
            key_questions=[],
        ),
        plan=[
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
        ],
        artifacts=[],
        review=None,
        result_summary="",
        context_summary={},
        created_at="2026-03-13T00:00:00Z",
        updated_at="2026-03-13T00:00:00Z",
        events=[],
    )


class FakeMissionOrchestrator:
    def __init__(self):
        self.run = _sample_run()

    def get_templates(self):
        return [
            MissionTemplate(
                id="custom",
                label="Custom Mission",
                description="Flexible agentic workflow",
                default_outputs=["research_brief", "final_dossier"],
                recommended_when=["Need a custom flow"],
            )
        ]

    def list_runs(self, limit: int = 20):
        return [
            {
                "run_id": self.run.run_id,
                "title": self.run.title,
                "status": self.run.status,
                "preset": self.run.preset,
                "goal": self.run.goal,
                "created_at": self.run.created_at,
                "updated_at": self.run.updated_at,
                "artifact_count": len(self.run.artifacts),
                "step_count": len(self.run.plan),
                "review_status": self.run.review.status if self.run.review else None,
            }
        ]

    def get_run(self, run_id: str):
        return self.run if run_id == self.run.run_id else None

    async def plan_mission(self, request):
        self.run.goal = request.goal
        return self.run

    def approve_run(self, run_id: str):
        self.run.status = "approved"
        return self.run

    async def execute_run(self, run_id: str, callback=None):
        if self.run.status == "awaiting_approval":
            raise PermissionError("Mission plan must be approved before execution.")

        artifact = {
            "artifact_id": "artifact_1",
            "kind": "final_dossier",
            "title": "Mission Test",
            "summary": "Compiled dossier",
            "source_step_id": "step_1",
            "file_name": "final_dossier.md",
            "file_path": "/tmp/final_dossier.md",
            "url": "/api/outputs/mission/mission_test_001/artifacts/final_dossier.md",
            "content_type": "text/markdown",
            "created_at": "2026-03-13T00:00:00Z",
            "preview": "# Final Dossier",
            "metadata": {},
        }
        review = MissionReview(
            status="pass",
            score=0.88,
            strengths=["Grounded"],
            risks=[],
            missing_items=[],
            recommended_changes=[],
            final_recommendation="Ready",
        )

        self.run.status = "completed"
        self.run.artifacts = [artifact]  # type: ignore[assignment]
        self.run.review = review
        self.run.plan[0].status = "completed"
        self.run.plan[1].status = "completed"
        self.run.result_summary = "Ready"

        if callback:
            await callback("run_started", {"run_id": self.run.run_id})
            await callback(
                "step_started",
                {"step_id": "step_1", "step_type": "research_brief", "title": "Research"},
            )
            await callback("artifact_created", {"step_id": "step_1", "artifact": artifact})
            await callback(
                "step_completed",
                {
                    "step_id": "step_1",
                    "step_type": "research_brief",
                    "summary": "done",
                    "artifact_ids": ["artifact_1"],
                },
            )
            await callback(
                "review_completed",
                {"step_id": "step_2", "review": review.model_dump()},
            )
            await callback(
                "run_completed",
                {
                    "run_id": self.run.run_id,
                    "artifact_count": 1,
                    "result_summary": "Ready",
                    "review": review.model_dump(),
                },
            )
        return self.run


@pytest.fixture
def fake_orchestrator():
    return FakeMissionOrchestrator()


@pytest.fixture
def client(monkeypatch, fake_orchestrator):
    monkeypatch.setattr(
        mission_router,
        "get_mission_orchestrator",
        lambda: fake_orchestrator,
    )
    app = FastAPI()
    app.include_router(mission_router.router, prefix="/api/v1/mission")

    with TestClient(app) as test_client:
        yield test_client


def test_templates_and_plan_endpoints(client: TestClient):
    templates = client.get("/api/v1/mission/templates")
    assert templates.status_code == 200
    assert templates.json()["presets"][0]["id"] == "custom"

    planned = client.post(
        "/api/v1/mission/plan",
        json={
            "goal": "Prepare a mission dossier",
            "preset": "custom",
            "desired_outputs": ["research_brief", "final_dossier"],
            "research_depth": "medium",
        },
    )
    assert planned.status_code == 200
    assert planned.json()["run"]["run_id"] == "mission_test_001"


def test_approve_and_execute_mission(client: TestClient):
    approve = client.post("/api/v1/mission/runs/mission_test_001/approve")
    assert approve.status_code == 200
    assert approve.json()["run"]["status"] == "approved"

    with client.websocket_connect("/api/v1/mission/run") as websocket:
        websocket.send_json({"run_id": "mission_test_001"})
        seen = []
        while True:
            message = websocket.receive_json()
            seen.append(message["type"])
            if message["type"] == "result":
                assert message["run"]["status"] == "completed"
                break

    assert "artifact_created" in seen
    assert "run_completed" in seen


def test_execute_without_approval_returns_error(client: TestClient, fake_orchestrator):
    fake_orchestrator.run.status = "awaiting_approval"
    with client.websocket_connect("/api/v1/mission/run") as websocket:
        websocket.send_json({"run_id": "mission_test_001"})
        message = websocket.receive_json()
        assert message["type"] == "error"
        assert message["code"] == "awaiting_approval"
