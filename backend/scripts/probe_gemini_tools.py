"""Manual check of Gemini function calling against the real API (never run by pytest).

    cd backend && uv run python -m scripts.probe_gemini_tools

It uses GEMINI_API_KEY_AGENT and the agent's hypothesis model and makes at most a few calls:
  1. a tool loop (one tool, the reason required, the thought signature echoed back),
  2. the same with the response JSON schema sent together with the tools
     (if this works, PRUNER_AGENT_SCHEMA_WITH_TOOLS=on saves one call per agent turn).
The disk cache is bypassed (a temporary folder), so it always talks to the API.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from pydantic import BaseModel

from pruner.agent.toolloop import AgentSession, ToolRunner
from pruner.agent.tools import Tool
from pruner.core.config import get_config
from pruner.core.llm import LLM, LLMError


class Answer(BaseModel):
    answer: str
    used_tool: bool


async def lookup(word: str) -> str:
    return json.dumps({"word": word, "meaning": "a probe value: 42"})


TOOL = Tool("lookup", "Look up the meaning of a word.",
            {"type": "object", "properties": {"word": {"type": "string"}},
             "required": ["word"]}, lookup)
PROMPT = "Use the lookup tool on the word 'pruner', then say what it returned."


async def main() -> None:
    import dataclasses

    base = get_config()
    for mode in ("off", "on"):
        cfg = dataclasses.replace(base, agent_schema_with_tools=mode)
        with tempfile.TemporaryDirectory() as tmp:
            llm = LLM(cfg, cache_dir=Path(tmp), role="agent")
            runner = ToolRunner([TOOL], cfg=cfg,
                                on_call=lambda r: print(f"  call {r.tool}({r.args}) "
                                                        f"reason={r.reason!r}"))
            try:
                out = await AgentSession(llm, cfg).run(
                    Answer, PROMPT, model=cfg.agent_hypothesis_model, purpose="probe",
                    runner=runner)
            except LLMError as e:
                print(f"schema_with_tools={mode}: FAILED: {e}")
                continue
            print(f"schema_with_tools={mode}: ok, stage_b={out.stage_b}, "
                  f"api_calls={out.tokens.calls}, answer={out.value}")


if __name__ == "__main__":
    asyncio.run(main())
