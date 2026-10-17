"""The research agent, on its own LLM instance (GEMINI_API_KEY_AGENT).

For now one turn: it reads the question, the user's specs and directives, and the objectives,
and returns a plan and a first answer. Given a ToolRunner it may call its read tools and the
findings-log tool on the way (see agent/toolloop.py); every call is logged with its reason. The
loop that proposes branches and runs experiments is not built yet.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from pruner.agent.toolloop import AgentSession, ToolRunner
from pruner.agent.tools import DEFAULT_TOOLS, Tool
from pruner.core import prompts
from pruner.core.config import Config, get_config
from pruner.core.llm import LLM, TokenCount
from pruner.core.models import Directive, Instruction, Objective, ToolCallRecord


class AgentReply(BaseModel):
    plan: list[str] = Field(default_factory=list)
    answer: str


@dataclass
class AgentResult:
    reply: AgentReply
    tokens: TokenCount = field(default_factory=TokenCount)
    records: list[ToolCallRecord] = field(default_factory=list)  # tool calls made, with reasons


class Agent:
    def __init__(self, llm: LLM, cfg: Config | None = None,
                 tools: Sequence[Tool] = DEFAULT_TOOLS) -> None:
        self.llm = llm
        self.cfg = cfg or get_config()
        self.tools = tuple(tools)

    @staticmethod
    def _tools_text(tools: Sequence[Tool]) -> str:
        return "\n".join(f"- {t.name}: {t.description}" for t in tools) or "(none)"

    async def run(self, *, question: str, objectives: Sequence[Objective],
                  instructions: Sequence[Instruction] = (),
                  directives: Sequence[Directive | str] = (),
                  runner: ToolRunner | None = None) -> AgentResult:
        """One turn. With `runner`, the agent may call its tools (Gemini function calling);
        without, it answers from the prompt alone."""
        tools = list(runner.tools.values()) if runner is not None else list(self.tools)
        prompt = prompts.render(
            "agent", question=question,
            instructions=prompts.render_instructions(instructions, directives),
            objectives=prompts.render_objectives(objectives), tools=self._tools_text(tools))
        out = await AgentSession(self.llm, self.cfg).run(
            AgentReply, prompt, model=self.cfg.agent_hypothesis_model, purpose="agent",
            runner=runner)
        return AgentResult(out.value, out.tokens, records=out.records)
