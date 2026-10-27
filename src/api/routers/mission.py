from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket

from src.agents.mission import MissionOrchestrator, MissionPlanRequest
from src.logging import get_logger
from src.services.config import load_config_with_main


router = APIRouter()

project_root = Path(__file__).resolve().parents[3]
config = load_config_with_main("main.yaml", project_root)
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = get_logger("Mission", log_dir=log_dir)


def get_mission_orchestrator() -> MissionOrchestrator:
    return MissionOrchestrator(config=config)


@router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "mission"}


@router.get("/templates")
async def get_templates():
    orchestrator = get_mission_orchestrator()
    return {"presets": [template.model_dump() for template in orchestrator.get_templates()]}


@router.get("/runs")
async def list_runs(limit: int = 20):
    orchestrator = get_mission_orchestrator()
    return {"runs": orchestrator.list_runs(limit=limit)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    orchestrator = get_mission_orchestrator()
    run = orchestrator.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Mission run not found")
    return {"run": run.model_dump()}


@router.post("/plan")
async def plan_mission(request: MissionPlanRequest):
    try:
        orchestrator = get_mission_orchestrator()
        run = await orchestrator.plan_mission(request)
        return {"success": True, "run": run.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"Mission planning failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/runs/{run_id}/approve")
async def approve_run(run_id: str):
    try:
        orchestrator = get_mission_orchestrator()
        run = orchestrator.approve_run(run_id)
        return {"success": True, "run": run.model_dump()}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(f"Mission approval failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.websocket("/run")
async def websocket_run_mission(websocket: WebSocket):
    await websocket.accept()

    async def safe_send(payload: dict):
        try:
            await websocket.send_json(payload)
        except Exception as send_err:
            logger.warning(f"Mission websocket send failed: {send_err}")

    try:
        payload = await websocket.receive_json()
        run_id = str(payload.get("run_id") or "").strip()
        if not run_id:
            await safe_send({"type": "error", "message": "run_id is required"})
            return

        orchestrator = get_mission_orchestrator()

        async def event_callback(event_type: str, event_payload: dict):
            await safe_send({"type": event_type, **event_payload})

        run = await orchestrator.execute_run(run_id, callback=event_callback)
        await safe_send({"type": "result", "run": run.model_dump()})
    except PermissionError as exc:
        await safe_send({"type": "error", "message": str(exc), "code": "awaiting_approval"})
    except FileNotFoundError as exc:
        await safe_send({"type": "error", "message": str(exc), "code": "not_found"})
    except Exception as exc:
        logger.error(f"Mission execution failed: {exc}")
        await safe_send({"type": "error", "message": str(exc), "code": "execution_failed"})
