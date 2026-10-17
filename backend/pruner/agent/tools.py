"""Tools the agent can call. None yet: the agent works from the prompt alone.

When tools are added, define each as a Tool and list it in DEFAULT_TOOLS; the agent shows their
names and descriptions in its prompt. Calling them (a function-calling loop) is not built yet.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema of the arguments
    run: Callable[..., Awaitable[str]]


DEFAULT_TOOLS: tuple[Tool, ...] = ()
