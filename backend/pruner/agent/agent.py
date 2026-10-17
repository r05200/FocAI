"""The research agent, on its own LLM instance (GEMINI_API_KEY_AGENT).

For now one turn: it reads the question, the user's specs and directives, and the objectives,
and returns a plan and a first answer. It has no tools yet (see tools.py), so nothing here searches,
runs or measures anything. The loop that proposes branches and runs experiments is not built.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from pruner.agent.tools import DEFAULT_TOOLS, Tool
from pruner.core import prompts
from pruner.core.config import Config, get_config
from pruner.core.llm import LLM, TokenCount
from pruner.core.models import Directive, Instruction, Objective


class AgentReply(BaseModel):
    plan: list[str] = Field(default_factory=list)
    answer: str


@dataclass
class AgentResult:
    reply: AgentReply
    tokens: TokenCount = field(default_factory=TokenCount)


class Agent:
    def __init__(self, llm: LLM, cfg: Config | None = None,
                 tools: Sequence[Tool] = DEFAULT_TOOLS) -> None:
        self.llm = llm
        self.cfg = cfg or get_config()
        self.tools = tuple(tools)

    def _tools_text(self) -> str:
        return "\n".join(f"- {t.name}: {t.description}" for t in self.tools) or "(none)"

    async def run(self, *, question: str, objectives: Sequence[Objective],
                  instructions: Sequence[Instruction] = (),
                  directives: Sequence[Directive | str] = ()) -> AgentResult:
        prompt = prompts.render(
            "agent", question=question,
            instructions=prompts.render_instructions(instructions, directives),
            objectives=prompts.render_objectives(objectives), tools=self._tools_text())
        gen = await self.llm.generate(AgentReply, prompt, model=self.cfg.strong_model,
                                      purpose="agent")
        return AgentResult(gen.value, gen.tokens)
