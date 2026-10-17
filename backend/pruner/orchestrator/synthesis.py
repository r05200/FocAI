"""The synthesis phase: judge an experiment, log the finding, choose the next action.

run(node) does, after the experiment:
  1. the post-score judge (supporting key, PostScorer) reads the result first; then the agent
     (the synthesis model, with vault/results tools and both write tools, every call logged
     with its reason) sees the judge's read -> measured / explanation / verdict / finding /
     next action;
  2. code overrides: a failed experiment is "inconclusive"; a refuted result the judge would park
     is parked (restorable) unless a person kept the node, otherwise the node is done;
  3. the finding goes to the shared findings log, the run vault (an idea) and, when supported or
     refuted, the run owner's vault as a "learned" item.
A research run (no files) judges the resources its search found instead
(synthesize_research.md): are they relevant to the objectives?
The baseline node gets no LLM synthesis: its numbers are what the others are compared with.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from pruner.agent.toolloop import AgentSession
from pruner.core import prompts
from pruner.core.config import Config, get_config
from pruner.core.llm import LLM, LLMError
from pruner.core.models import (
    Finding,
    HypothesisVerdict,
    LogEntry,
    NextAction,
    Node,
    RunIdea,
    Synthesis,
)
from pruner.orchestrator.actions import NODE_ACTIONS, experiments_left, room_under
from pruner.orchestrator.context import RunView, ancestors, build_context
from pruner.orchestrator.experiment import compact, describe
from pruner.pruning import postscorer as post
from pruner.pruning.postscorer import PostScorer

if TYPE_CHECKING:
    from pruner.runs.manager import LiveRun, RunManager

log = logging.getLogger(__name__)


class SynthesisOutput(BaseModel):
    measured: str
    explanation: str = ""
    verdict: HypothesisVerdict
    confidence: float = Field(default=0.5, ge=0, le=1)
    finding: str
    next_action: NextAction = "stop"
    next_reason: str = ""
    action_targets: list[str] = Field(default_factory=list)
    action_brief: str = ""
    idea_title: str = ""


def baseline_text(nodes: list[Node]) -> str:
    root = next((n for n in nodes if n.parent_id is None), None)
    if root is None or root.experiment is None:
        return "(not measured)"
    return describe(root.experiment)


def action_menu(state: LiveRun, node: Node) -> str:
    run, nodes = state.run, state.nodes
    lines = []
    for action in (*NODE_ACTIONS, "new_hypothesis", "stop"):
        if action == "stop":
            ok, why = True, ""
        elif action == "new_hypothesis":
            parent = next((n for n in nodes if n.id == node.parent_id), node)
            ok = room_under(run, nodes, parent) > 0
            why = "" if ok else "no room next to this node"
        elif action in ("combine", "transfer") and node.verdict != "supported":
            ok, why = None, "only after a supported result"  # decided once the verdict is known
        else:
            ok = room_under(run, nodes, node) > 0
            why = "" if ok else "depth or budget limit"
        mark = "allowed" if ok else ("allowed if supported" if ok is None else f"not allowed: "
                                                                                f"{why}")
        lines.append(f"- {action} ({mark})")
    left = experiments_left(run, nodes)
    return "\n".join(lines) + f"\n({left} experiment(s) left after the queued ones)"


class SynthesisPhase:
    def __init__(self, llm: LLM, postscorer: PostScorer, cfg: Config | None = None) -> None:
        self.llm = llm
        self.postscorer = postscorer
        self.cfg = cfg or get_config()

    async def run(self, host: RunManager, state: LiveRun, node: Node) -> Synthesis:
        run = state.run
        assert node.experiment is not None
        view = RunView(run=run, nodes=state.nodes, findings=state.findings,
                       dead_ends=state.dead_ends, workspace=state.workspace)
        values = build_context(view, node, self.cfg)
        change = (state.workspace.diff(node.base_version, node.version)
                  if state.workspace and node.base_version and node.version else "(none)")
        research = state.workspace is None
        baseline = ("(none: this run searches for resources)" if research
                    else baseline_text(state.nodes))

        async def judge() -> str:
            try:
                scored = await self.postscorer.score(
                    node, question=run.question, objectives=run.objectives,
                    result=describe(node.experiment),
                    people=run.vault_people, baseline=baseline, dead_ends=state.dead_ends,
                    instructions=run.instructions, directives=run.directives)
            except (LLMError, ValueError) as e:  # the judge is advice; synthesis goes on
                log.warning("post-score of %s failed: %s", node.id, e)
                return "(the judge could not score this result)"
            post.apply(node, scored)
            return f"{scored.post_score * 10:.1f} / 10: {scored.decision.reason}"

        kept_by_hand = node.decided_by == "human" and node.decision is not None \
            and node.decision.verdict == "keep"
        judge_task = asyncio.create_task(judge())
        hypothesis = node.hypothesis
        shared = {
            "question": values["question"], "instructions": values["instructions"],
            "objectives": values["objectives"], "ancestors": values["ancestors"],
            "findings": values["findings"], "budget": values["budget"],
            "hypothesis": (f"{hypothesis.statement}\nExpected: {hypothesis.expected_signal}"
                           if hypothesis else node.description),
            "result": describe(node.experiment), "judge": await judge_task,
            "actions": action_menu(state, node)}
        prompt = (prompts.render("synthesize_research", **shared) if research
                  else prompts.render("synthesize", command=values["command"],
                                      change=change[:4000] or "(none)", baseline=baseline,
                                      **shared))
        runner = host._runner(state, node, "synthesis")
        out = await AgentSession(self.llm, self.cfg).run(
            SynthesisOutput, prompt, model=self.cfg.agent_synthesis_model, purpose="synthesis",
            runner=runner)
        node.tokens.agent += out.tokens.total
        if out.records:
            node.tool_calls["synthesis"] = node.tool_calls.get("synthesis", 0) + len(out.records)
        s = out.value
        verdict = "inconclusive" if node.experiment.error else s.verdict
        synthesis = Synthesis(measured=s.measured, explanation=s.explanation, verdict=verdict,
                              confidence=s.confidence, finding=s.finding,
                              next_action=s.next_action, next_reason=s.next_reason,
                              action_targets=s.action_targets, action_brief=s.action_brief)
        compact(node.experiment)  # the judged text is in the node's log; keep the node light
        node.synthesis, node.verdict = synthesis, verdict
        node.summary = s.finding
        node.phase = "complete"
        if kept_by_hand and node.decided_by != "human":
            node.decided_by = "human"  # a person's keep wins over the judge's park
            if node.status == "parked":
                host._log(state, node.id, LogEntry(
                    kind="decision", title="Kept by you despite the judge",
                    text=node.decision.reason if node.decision else "", phase="synthesis"))
                node.status = "done"
        if node.experiment.error:
            node.status = "failed"
        elif verdict == "refuted" and node.status == "parked":
            pass  # the judge parked it and the agent agrees it did not work: keep it parked
        else:
            node.status = "done"
        host._log(state, node.id, LogEntry(
            kind="decision", title=f"Verdict: {verdict} ({s.confidence:.0%} sure)",
            text=f"Measured: {s.measured}\nExplanation (not verified): {s.explanation}\n"
                 f"Next: {s.next_action} - {s.next_reason}", phase="synthesis"))
        await self._record(host, state, node, s.idea_title or s.finding)
        return synthesis

    async def _record(self, host: RunManager, state: LiveRun, node: Node, title: str) -> None:
        run = state.run
        s = node.synthesis
        assert s is not None and node.experiment is not None
        host._add_finding(state, Finding(
            run_id=run.id, node_id=node.id, family=node.family, verdict=s.verdict, text=s.finding,
            evidence_node_ids=[node.id], metrics=node.experiment.metrics))
        branch = " > ".join(n.id for n in ancestors(state.nodes, node))
        host._add_idea(state, RunIdea(branch=branch, title=title, summary=s.measured,
                                      node_ids=[node.id]))
        if s.verdict in ("supported", "refuted") and host.vault is not None:
            try:
                await host.vault.ingest_learned(
                    run.primary_person, title=s.finding,
                    summary=f"{s.verdict.capitalize()} in run {run.id}: {s.measured}",
                    source_text=f"{node.full_text()}\n{describe(node.experiment)}")
            except (LLMError, OSError) as e:  # the vault is a bonus; the run goes on
                log.warning("could not file the finding of %s in the vault: %s", node.id, e)
