"""Running the agent with tools: the per-phase tool budget, the required reason, and logging.

ToolRunner wraps one phase's tools:
  - Every tool's schema gets a required `reason` argument. The reason is taken out before the tool
    runs and logged with the call (ToolCallRecord), so a node's log says why each tool was called.
    A call without a reason is refused with an error the model can read.
  - Read tools share one budget (cfg.tool_calls_per_phase); each write tool has its own
    (cfg.write_tool_calls_per_phase), so writing a finding never uses up the reading budget.
  - The same call (tool and arguments) made twice in a run returns the first result again, marked
    as cached, and costs nothing.

AgentSession.run(schema, prompt, runner) gets a structured answer in two stages, because Gemini 3.x
is not known to accept tools and a JSON schema together:
  A. the tool loop (LLM.run_tools) without a schema; the prompt asks for the final JSON only. If
     that text validates, it is the answer (the usual case when no tool is called: one API call).
  B. otherwise one ordinary structured call (LLM.generate) with the tool calls and their results
     pasted in as evidence.
cfg.agent_schema_with_tools = "on" also sends the schema in stage A; "auto" does that until the
API refuses it once (HTTP 400), then stays "off" for the rest of the process.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from pruner.agent.tools import Tool
from pruner.core.config import Config, get_config
from pruner.core.llm import LLM, LLMError, TokenCount, ToolTranscript
from pruner.core.models import AgentPhase, ToolCallRecord

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

REASON_SCHEMA = {"type": "string",
                 "description": "One sentence: why you are calling this tool now."}
PREVIEW_CHARS = 600  # how much of a tool's result goes into the node's log


def _error(message: str) -> str:
    return json.dumps({"error": message})


def with_reason(parameters: dict[str, Any]) -> dict[str, Any]:
    """A tool's JSON schema with the required `reason` argument added."""
    schema = json.loads(json.dumps(parameters))  # a deep copy
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})["reason"] = REASON_SCHEMA
    required = [r for r in schema.get("required", []) if r != "reason"]
    schema["required"] = [*required, "reason"]
    return schema


# Read tools whose answer changes as the run goes on (the tree's results): never reused.
FRESH_TOOLS = frozenset({"get_results"})


class ToolRunner:
    """One phase's tools, with their budgets. `on_call` is told about every call that ran."""

    def __init__(self, tools: Sequence[Tool], *, phase: AgentPhase = "hypothesis",
                 cfg: Config | None = None,
                 on_call: Callable[[ToolCallRecord], None] | None = None,
                 seen: dict[str, str] | None = None, scope: str = "") -> None:
        cfg = cfg or get_config()
        self.tools = {t.name: t for t in tools}
        self.phase = phase
        self.on_call = on_call
        self.read_budget = cfg.tool_calls_per_phase
        self.write_budget = cfg.write_tool_calls_per_phase
        self.used: dict[str, int] = {}  # "read", or a write tool's name -> calls made
        self.records: list[ToolCallRecord] = []
        self.seen = seen if seen is not None else {}  # (tool, args) -> result, shared per run
        # what the reused results depend on (the code version read_file reads): a call made for
        # another version is not "the same call"
        self.scope = scope

    @property
    def max_calls(self) -> int:
        """How many calls the loop may make before tools are switched off."""
        writes = sum(1 for t in self.tools.values() if t.kind == "write")
        has_reads = any(t.kind == "read" for t in self.tools.values())
        return (self.read_budget if has_reads else 0) + writes * self.write_budget

    def declarations(self) -> list[dict[str, Any]]:
        return [{"name": t.name, "description": t.description,
                 "parameters": with_reason(t.parameters)} for t in self.tools.values()]

    def _budget_left(self, tool: Tool) -> bool:
        bucket = "read" if tool.kind == "read" else tool.name
        limit = self.read_budget if tool.kind == "read" else self.write_budget
        if self.used.get(bucket, 0) >= limit:
            return False
        self.used[bucket] = self.used.get(bucket, 0) + 1
        return True

    async def handle(self, name: str, args: dict[str, Any]) -> str:
        tool = self.tools.get(name)
        if tool is None:
            return _error(f"no tool named {name!r}; available: {', '.join(self.tools)}")
        args = dict(args)
        reason = str(args.pop("reason", "") or "").strip()
        if not reason:
            return _error("every tool call needs a 'reason': one sentence on why you call it")
        key = json.dumps([name, args, self.scope], sort_keys=True, default=str)
        cached = key in self.seen and name not in FRESH_TOOLS
        if cached:
            result = self.seen[key]
        elif not self._budget_left(tool):
            return _error(f"the {tool.kind} tool budget for this phase is used up; answer now")
        else:
            result = await tool.call(args)
            if tool.kind == "read" and name not in FRESH_TOOLS:  # writes never replayed
                self.seen[key] = result
        record = ToolCallRecord(phase=self.phase, tool=name, args=args, reason=reason,
                                result_preview=result[:PREVIEW_CHARS], cached=cached)
        self.records.append(record)
        if self.on_call is not None:
            self.on_call(record)
        if cached:
            return json.dumps({"note": "same call as before in this run; result reused",
                               "result": json.loads(result) if _is_json(result) else result})
        return result


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def _strip_fences(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    return (match.group(1) if match else text).strip()


@dataclass
class SessionResult(Generic[T]):
    value: T
    tokens: TokenCount
    transcript: ToolTranscript | None = None
    stage_b: bool = False  # a second, structured call was needed
    records: list[ToolCallRecord] = field(default_factory=list)


_schema_with_tools_refused = False  # "auto": the API refused tools + schema once in this process


class AgentSession:
    def __init__(self, llm: LLM, cfg: Config | None = None) -> None:
        self.llm = llm
        self.cfg = cfg or get_config()

    def _schema_mode(self) -> bool:
        mode = self.cfg.agent_schema_with_tools
        return mode == "on" or (mode == "auto" and not _schema_with_tools_refused)

    async def run(self, schema: type[T], prompt: str, *, model: str, purpose: str,
                  runner: ToolRunner | None = None, system: str | None = None
                  ) -> SessionResult[T]:
        """The agent's structured answer, with tools if `runner` has any (see the module doc)."""
        global _schema_with_tools_refused
        if runner is None or not runner.tools:
            gen = await self.llm.generate(schema, prompt, model=model, purpose=purpose,
                                          system=system)
            return SessionResult(gen.value, gen.tokens)

        json_schema = schema.model_json_schema()
        stage_a = (f"{prompt}\n\nUse the tools only if they help. When you are done, reply with "
                   f"the final answer as JSON only, matching this schema:\n"
                   f"{json.dumps(json_schema)}")
        with_schema = self._schema_mode()
        try:
            transcript = await self.llm.run_tools(
                stage_a, runner.declarations(), runner.handle, model=model, purpose=purpose,
                system=system, max_calls=runner.max_calls,
                response_schema=json_schema if with_schema else None)
        except LLMError as e:
            if not (with_schema and self.cfg.agent_schema_with_tools == "auto" and "400" in str(e)):
                raise
            _schema_with_tools_refused = True
            log.warning("the API refused tools with a response schema; using two stages")
            transcript = await self.llm.run_tools(
                stage_a, runner.declarations(), runner.handle, model=model, purpose=purpose,
                system=system, max_calls=runner.max_calls)
        tokens = TokenCount()
        tokens.add(transcript.tokens)
        try:
            value = schema.model_validate_json(_strip_fences(transcript.final_text))
            return SessionResult(value, tokens, transcript, records=list(runner.records))
        except ValidationError:
            pass
        stage_b = (f"{prompt}\n\nWhat your tool calls returned (use it; do not call tools "
                   f"now):\n{transcript.evidence()}")
        gen = await self.llm.generate(schema, stage_b, model=model, purpose=purpose,
                                      system=system)
        tokens.add(gen.tokens)
        return SessionResult(gen.value, tokens, transcript, stage_b=True,
                             records=list(runner.records))
