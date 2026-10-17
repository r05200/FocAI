"""FastAPI app. Run with:  cd backend && uv run uvicorn pruner.api.app:app --reload --port 8000
Interactive docs for every route are served at /docs."""

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pruner.core.config import get_config

from . import directives, nodes, questions, replays, runs, vault


def create_app() -> FastAPI:
    app = FastAPI(title="Pruner", version="0.1.0")
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

    for module in (runs, nodes, questions, vault, directives, replays):
        api.include_router(module.router)
    app.include_router(api)
    return app


app = create_app()
