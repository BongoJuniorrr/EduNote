import asyncio
from contextlib import asynccontextmanager, suppress
import os
from pathlib import Path
import time

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.middleware.rate_limit import InMemoryRateLimitMiddleware
from src.api.routers import (
    about,
    agent_config,
    chat,
    co_writer,
    config,
    dashboard,
    document_processing,
    edu_studio,
    guide,
    ideagen,
    jobs,
    learning,
    knowledge,
    mission,
    notebook,
    ocr,
    question,
    research,
    settings,
    slide_pro,
    solve,
    storage,
    system,
    vgu_course,
)
from src.logging import get_logger

# Note: Don't set service_prefix here - start_web.py already adds [Backend] prefix
logger = get_logger("API")

CONFIG_DRIFT_ERROR_TEMPLATE = (
    "Configuration Drift Detected: Tools {drift} found in agents.yaml "
    "investigate.valid_tools but missing from main.yaml solve.valid_tools. "
    "Add these tools to main.yaml solve.valid_tools or remove them from "
    "agents.yaml investigate.valid_tools."
)

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in _TRUE_VALUES


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _validate_production_security() -> None:
    if os.getenv("EDUNOTE_ENV", "development").strip().lower() != "production":
        return
    if "*" in _build_cors_origins()[0]:
        raise RuntimeError("Wildcard CORS is not allowed in production")


def _build_cors_origins() -> tuple[list[str], str | None]:
    """
    Build CORS origin settings from environment.

    Supported env vars:
    - CORS_ALLOWED_ORIGINS / CORS_ALLOW_ORIGINS: comma-separated origins
    - CORS_ALLOWED_ORIGIN_REGEX / CORS_ALLOW_ORIGIN_REGEX: regex pattern
    - FRONTEND_ORIGIN: single origin shortcut
    """
    raw_origins = (
        os.getenv("CORS_ALLOWED_ORIGINS") or os.getenv("CORS_ALLOW_ORIGINS") or ""
    ).strip()

    if raw_origins:
        origins = _split_csv(raw_origins)
    else:
        # Safe local defaults for development.
        origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3782",
            "http://127.0.0.1:3782",
        ]

    frontend_origin = (os.getenv("FRONTEND_ORIGIN") or "").strip()
    if frontend_origin:
        origins.append(frontend_origin)

    # Normalize and de-duplicate while keeping stable order.
    normalized: list[str] = []
    seen: set[str] = set()
    for origin in origins:
        clean = origin.rstrip("/")
        if clean and clean not in seen:
            seen.add(clean)
            normalized.append(clean)

    origin_regex = (
        os.getenv("CORS_ALLOWED_ORIGIN_REGEX") or os.getenv("CORS_ALLOW_ORIGIN_REGEX") or ""
    ).strip() or None

    return normalized, origin_regex


async def _prewarm_embedding_client(app: FastAPI) -> None:
    """
    Warm up embedding model in background to avoid first-chat cold start latency.

    By default this only runs for local embedding backends.
    Set EMBEDDING_PREWARM_FORCE=true to force prewarm for non-local providers.
    """
    started_at = time.perf_counter()

    try:
        from src.services.embedding import get_embedding_client

        client = get_embedding_client()
        binding = getattr(getattr(client, "config", None), "binding", "unknown")
        force_prewarm = _env_flag("EMBEDDING_PREWARM_FORCE", "false")

        if binding not in {"huggingface", "ollama", "lm_studio"} and not force_prewarm:
            logger.info(f"Embedding prewarm skipped for non-local provider: {binding}")
            return

        # A tiny payload is enough to trigger model load/caching.
        await client.embed(["embedding prewarm"])
        elapsed = time.perf_counter() - started_at
        logger.info(f"Embedding prewarm completed in {elapsed:.2f}s (binding={binding})")
    except Exception as e:
        logger.warning(f"Embedding prewarm failed: {e}")
    finally:
        app.state.embedding_prewarm_done = True


def validate_tool_consistency():
    """
    Validate that the tools configured for agents are consistent with the main application
    configuration.

    This function loads the main configuration (``main.yaml``) and the agents configuration
    (``agents.yaml``) from the project root and compares:

    * ``solve.valid_tools`` in ``main.yaml``
    * ``investigate.valid_tools`` in ``agents.yaml``

    All tools referenced by agents must be present in the main configuration. If any tools are
    defined for agents that are not listed in the main configuration, a ``RuntimeError`` is
    raised describing the drift. The error is logged and re-raised, which causes the FastAPI
    application startup to fail when this function is called from the ``lifespan`` handler.

    Impact on startup
    ------------------
    This validation runs during application startup. Any configuration drift will:

    * Be logged as an error with details about the unknown tools.
    * Prevent the API from starting until the configuration is corrected.

    How to resolve configuration drift
    ----------------------------------
    If startup fails with a configuration drift error:

    1. Inspect the set of tools reported in the error message.
    2. Either:
       * Add the missing tools to ``solve.valid_tools`` in ``main.yaml``, **or**
       * Remove or rename the offending tools from ``investigate.valid_tools`` in ``agents.yaml``.
    3. Restart the application after updating the configuration files.

    Example of aligned configuration
    --------------------------------
    ``main.yaml``::

        solve:
          valid_tools:
            - web_search
            - code_execution

    ``agents.yaml``::

        investigate:
          valid_tools:
            - web_search

    In this case, validation passes because ``investigate.valid_tools`` is a subset of
    ``solve.valid_tools``.

    Example of configuration drift
    ------------------------------
    ``agents.yaml``::

        investigate:
          valid_tools:
            - web_search
            - unknown_tool

    Here, ``unknown_tool`` is not present in ``solve.valid_tools`` in ``main.yaml``, so
    validation will fail and prevent the application from starting until the configurations
    are aligned.
    """
    try:
        from src.services.config import load_config_with_main

        project_root = Path(__file__).parent.parent.parent
        main_config = load_config_with_main("main.yaml", project_root)
        agent_config_data = load_config_with_main("agents.yaml", project_root)

        main_tools = set(main_config.get("solve", {}).get("valid_tools", []))
        agent_tools = set(agent_config_data.get("investigate", {}).get("valid_tools", []))

        if not agent_tools.issubset(main_tools):
            drift = agent_tools - main_tools
            raise RuntimeError(CONFIG_DRIFT_ERROR_TEMPLATE.format(drift=drift))
    except RuntimeError:
        logger.exception("Configuration validation failed")
        raise
    except Exception:
        logger.exception("Failed to load configuration for validation")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifecycle management
    Gracefully handle startup and shutdown events, avoid CancelledError
    """
    # Execute on startup
    logger.info("Application startup")
    _validate_production_security()

    # Validate configuration consistency
    validate_tool_consistency()

    # Initialize LLM client early to set environment variables for LightRAG
    # LightRAG reads OPENAI_API_KEY from os.environ internally, so we must
    # set it before any RAG operations can happen
    try:
        from src.services.llm import get_llm_client

        llm_client = get_llm_client()
        logger.info(f"LLM client initialized: model={llm_client.config.model}")
    except Exception as e:
        logger.warning(f"Failed to initialize LLM client at startup: {e}")

    app.state.embedding_prewarm_done = False
    app.state.embedding_prewarm_task = None

    if _env_flag("EMBEDDING_PREWARM", "true"):
        prewarm_mode = os.getenv("EMBEDDING_PREWARM_MODE", "background").strip().lower()
        if prewarm_mode == "blocking":
            logger.info("Embedding prewarm started (mode=blocking)")
            await _prewarm_embedding_client(app)
        else:
            logger.info("Embedding prewarm scheduled (mode=background)")
            app.state.embedding_prewarm_task = asyncio.create_task(_prewarm_embedding_client(app))
    else:
        logger.info("Embedding prewarm disabled (EMBEDDING_PREWARM=false)")

    yield
    # Execute on shutdown
    prewarm_task = getattr(app.state, "embedding_prewarm_task", None)
    if prewarm_task and not prewarm_task.done():
        prewarm_task.cancel()
        with suppress(asyncio.CancelledError):
            await prewarm_task

    logger.info("Application shutdown")


app = FastAPI(
    title="EduNote API",
    version="1.0.0",
    lifespan=lifespan,
    # Disable automatic trailing slash redirects to prevent protocol downgrade issues
    # when deployed behind HTTPS reverse proxies (e.g., nginx).
    # Without this, FastAPI's 307 redirects may change HTTPS to HTTP.
    # See: https://github.com/BongoJuniorrr/EduNote/issues/112
    redirect_slashes=False,
)

# Configure CORS
cors_origins, cors_origin_regex = _build_cors_origins()
logger.info(
    f"CORS configured with {len(cors_origins)} explicit origins"
    + (f" and regex '{cors_origin_regex}'" if cors_origin_regex else "")
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(InMemoryRateLimitMiddleware)
from src.api.middleware.metrics import HttpMetricsMiddleware, metrics_response
app.add_middleware(HttpMetricsMiddleware)
from src.api.middleware.generated_html import GeneratedHtmlIsolationMiddleware
app.add_middleware(GeneratedHtmlIsolationMiddleware)
app.add_api_route("/metrics", metrics_response, methods=["GET"], include_in_schema=False)

# Mount user directory as static root for generated artifacts
# This allows frontend to access generated artifacts (images, PDFs, etc.)
# URL: /api/outputs/solve/solve_xxx/artifacts/image.png
# Physical Path: EduNote/data/user/solve/solve_xxx/artifacts/image.png
project_root = Path(__file__).parent.parent.parent
user_dir = project_root / "data" / "user"

# Initialize user directories on startup
try:
    from src.services.setup import init_user_directories

    init_user_directories(project_root)
except Exception:
    # Fallback: just create the main directory if it doesn't exist
    if not user_dir.exists():
        user_dir.mkdir(parents=True)

# Expose generated artifacts, never the settings directory containing API keys.
for module in (
    "solve",
    "question",
    "research",
    "guide",
    "co_writer",
    "co-writer",
    "edu-studio",
    "slide-pro",
    "notebook",
    "mission",
    "audio",
    "chat",
):
    output_dir = user_dir / module
    if module == "audio":
        from src.services.storage import get_storage_service

        output_dir = get_storage_service().user_root("local") / "audio"
    output_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        f"/api/outputs/{module}",
        StaticFiles(directory=str(output_dir)),
        name=f"outputs-{module}",
    )


# Include routers
app.include_router(solve.router, prefix="/api/v1", tags=["solve"])
app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
app.include_router(question.router, prefix="/api/v1/question", tags=["question"])
app.include_router(research.router, prefix="/api/v1/research", tags=["research"])
app.include_router(
    knowledge.router,
    prefix="/api/v1/knowledge",
    tags=["knowledge"],
)
app.include_router(mission.router, prefix="/api/v1/mission", tags=["mission"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(co_writer.router, prefix="/api/v1/co_writer", tags=["co_writer"])
app.include_router(notebook.router, prefix="/api/v1/notebook", tags=["notebook"])
app.include_router(guide.router, prefix="/api/v1/guide", tags=["guide"])
app.include_router(ideagen.router, prefix="/api/v1/ideagen", tags=["ideagen"])
app.include_router(learning.router, prefix="/api/v1/learning", tags=["learning"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["jobs"])
app.include_router(edu_studio.router, prefix="/api/v1/edu-studio", tags=["edu-studio"])
if _env_flag("ENABLE_LEGACY_SLIDE_PRO", "false"):
    public_slide_pro = APIRouter()
    public_slide_pro.add_api_route("/health", slide_pro.health_check, methods=["GET"])
    public_slide_pro.add_api_route("/templates", slide_pro.get_templates, methods=["GET"])
    app.include_router(public_slide_pro, prefix="/api/v1/slide-pro", tags=["slide-pro"])
    app.include_router(
        slide_pro.router,
        prefix="/api/v1/slide-pro",
        tags=["slide-pro"],
    )
    logger.info("Legacy Slide Pro API enabled at /api/v1/slide-pro")
else:
    logger.info("Legacy Slide Pro API disabled (set ENABLE_LEGACY_SLIDE_PRO=true to re-enable)")
app.include_router(document_processing.router, prefix="/api/v1/config/documents", tags=["documents"])
app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(storage.router, prefix="/api/v1/storage", tags=["storage"])
app.include_router(ocr.router, prefix="/api/v1/ocr/jobs", tags=["ocr"])
app.include_router(system.router, prefix="/api/v1/system", tags=["system"])
app.include_router(config.router, prefix="/api/v1/config", tags=["config"])
app.include_router(agent_config.router, prefix="/api/v1/agent-config", tags=["agent-config"])
app.include_router(vgu_course.router, prefix="/api/v1", tags=["vgu-course"])
app.include_router(about.router, prefix="/api/v1/about", tags=["about"])


@app.get("/")
async def root():
    return {"message": "Welcome to EduNote API"}


@app.get("/health")
async def health_check():
    """Health check endpoint for Docker/Kubernetes."""
    return {"status": "healthy", "service": "edunote-api"}


if __name__ == "__main__":
    from pathlib import Path

    import uvicorn

    # Get project root directory
    project_root = Path(__file__).parent.parent.parent

    # Ensure project root is in Python path
    import sys

    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # Get port from configuration
    from src.services.setup import get_backend_port

    backend_port = get_backend_port(project_root)

    # Configure reload_excludes with absolute paths to properly exclude directories
    venv_dir = project_root / "venv"
    data_dir = project_root / "data"
    reload_excludes = [
        str(d)
        for d in [
            venv_dir,
            project_root / ".venv",
            data_dir,
            project_root / "web" / "node_modules",
            project_root / "web" / ".next",
            project_root / ".git",
        ]
        if d.exists()
    ]

    uvicorn.run(
        "api.main:app",
        host=os.getenv("EDUNOTE_LISTEN_HOST", "127.0.0.1"),
        port=backend_port,
        reload=True,
        reload_excludes=reload_excludes,
    )
