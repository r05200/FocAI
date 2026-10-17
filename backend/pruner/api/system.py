"""Read-only settings for the UI."""

from fastapi import APIRouter

from pruner.core.config import get_config
from pruner.core.models import PublicConfig

router = APIRouter(prefix="/config", tags=["meta"])


@router.get("")
async def get_public_config() -> PublicConfig:
    """Models, caps and thresholds (scores on the 1 to 10 scale). No secrets or paths."""
    cfg = get_config()
    return PublicConfig(**{f: getattr(cfg, f) for f in PublicConfig.model_fields})
