"""FastAPI app. Run with:  cd backend && uv run uvicorn pruner.api.app:app --reload --port 8000
Interactive docs for every route are served at /docs."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pruner.api.deps import get_run_manager
from pruner.core.config import get_config

from . import (
    directives,
    nodes,
    prompts,
    questions,
    replays,
    run_vault,
    runs,
    suggestions,
    system,
    vault,
)

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """At server start, runs left "running" by a restart come back paused (RunManager.recover)."""
    try:
        paused = await get_run_manager().recover()
        if paused:
            log.warning("recovered %d run(s), paused: %s", len(paused), ", ".join(paused))
    except Exception:  # a broken saved run must not stop the server from starting
        log.exception("could not recover the runs left running by the last server")
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Pruner", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(get_config().cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = APIRouter(prefix="/api")

    @api.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    for module in (runs, run_vault, nodes, questions, suggestions, vault, directives, prompts,
                   system, replays):
        api.include_router(module.router)
    app.include_router(api)
    return app


app = create_app()
