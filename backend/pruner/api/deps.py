"""Shared singletons for route handlers. Tests swap them with app.dependency_overrides.

There are three LLM instances, each with its own Gemini API key (and so its own quota and token
usage):
- get_supporting_llm (GEMINI_API_KEY_SUPPORTING): the vault store, the scorers and the objective
  maker all share it.
- get_agent_llm (GEMINI_API_KEY_AGENT): the research agent's own LLM (see get_agent).
- get_fork_agent_llm (GEMINI_API_KEY_FORK_AGENT): the amendment re-rating that forks come from.
"""

from functools import lru_cache

from pruner.agent.agent import Agent
from pruner.agent.amend import AmendObjectivesAgent
from pruner.core.llm import LLM
from pruner.orchestrator.loop import Orchestrator
from pruner.pruning.postscorer import PostScorer
from pruner.pruning.prescorer import PreScorer
from pruner.runs.manager import RunManager
from pruner.runs.objectives import ObjectiveMaker
from pruner.runs.store import RunStore
from pruner.vault.directives import DirectiveStore
from pruner.vault.store import VaultStore


@lru_cache(maxsize=1)
def get_supporting_llm() -> LLM:
    return LLM(role="supporting")


@lru_cache(maxsize=1)
def get_agent_llm() -> LLM:
    return LLM(role="agent")


@lru_cache(maxsize=1)
def get_fork_agent_llm() -> LLM:
    return LLM(role="fork_agent")


@lru_cache(maxsize=1)
def get_vault_store() -> VaultStore:
    return VaultStore(llm=get_supporting_llm())


@lru_cache(maxsize=1)
def get_directive_store() -> DirectiveStore:
    return DirectiveStore()


@lru_cache(maxsize=1)
def get_run_store() -> RunStore:
    return RunStore()


@lru_cache(maxsize=1)
def get_prescorer() -> PreScorer:
    return PreScorer(get_vault_store(), get_supporting_llm())


@lru_cache(maxsize=1)
def get_postscorer() -> PostScorer:
    return PostScorer(get_vault_store(), get_supporting_llm())


@lru_cache(maxsize=1)
def get_objective_maker() -> ObjectiveMaker:
    return ObjectiveMaker(get_supporting_llm())


@lru_cache(maxsize=1)
def get_agent() -> Agent:
    return Agent(get_agent_llm())


@lru_cache(maxsize=1)
def get_amend_agent() -> AmendObjectivesAgent:
    # The amendment re-rating (what a fork is suggested from) runs on the fork agent's own LLM.
    return AmendObjectivesAgent(PreScorer(get_vault_store(), get_fork_agent_llm()), get_run_store())


@lru_cache(maxsize=1)
def get_run_manager() -> RunManager:
    return RunManager(get_run_store(), get_agent(), get_objective_maker(),
                      amender=get_amend_agent(), vault=get_vault_store(),
                      orchestrator=get_orchestrator())


@lru_cache(maxsize=1)
def get_orchestrator() -> Orchestrator:
    return Orchestrator(get_agent_llm(), get_prescorer(), get_postscorer())
