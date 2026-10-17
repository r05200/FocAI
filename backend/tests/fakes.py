"""Test doubles: no network, deterministic."""

from __future__ import annotations

import hashlib
import re
from types import SimpleNamespace
from typing import Any

import numpy as np

from pruner.core.llm import Generated, TokenCount
from pruner.pruning.postscorer import PostScoreOutput
from pruner.pruning.prescorer import CandidateRating, PreScoreBatch
from pruner.runs.objectives import ObjectiveDraft
from pruner.vault.store import IngestDraft, RelationJudgement, RelationOutput

DIM = 64


def bag_of_words(text: str, dim: int = DIM) -> list[float]:
    """Hashed word counts: texts sharing words get high cosine similarity."""
    v = np.zeros(dim)
    for word in re.findall(r"[a-z]+", text.lower()):
        v[int(hashlib.md5(word.encode()).hexdigest(), 16) % dim] += 1
    return v.tolist()


class FakeLLM:
    """Stands in for pruner.llm.LLM inside VaultStore."""

    def __init__(self, relation: str = "supports", pre_score: float = 0.8,
                 post_score: float = 0.8,
                 progress: tuple[str, ...] = ()) -> None:
        self.relation = relation
        self.pre_score = pre_score
        self.post_score = post_score
        self.objectives = ["Find methods that cut cost", "Show the accuracy cost"]
        self.progress = list(progress)
        self.prompts: list[str] = []

    async def generate(self, schema: Any, prompt: str, **_: Any) -> Generated:
        self.prompts.append(prompt)
        if schema is IngestDraft:
            text = prompt.split('"""')[1].strip()
            words = text.split()
            value = IngestDraft(title=" ".join(words[:5]), summary=text[:80],
                                tags=["Long Context", "kv cache", "long-context"],
                                investigate=bool(
                                    re.search(r"investigate|look into", text, re.IGNORECASE)))
        elif schema is RelationOutput:
            ids = re.findall(r"^(v_\w+) \(", prompt, re.MULTILINE)
            value = RelationOutput(relations=[
                RelationJudgement(neighbor_id=i, relation=self.relation,
                                  reason="Fake reason\nspanning lines.") for i in ids])
        elif schema is PreScoreBatch:
            blocks = re.split(r"^Candidate ", prompt, flags=re.MULTILINE)[1:]
            ratings = []
            for block in blocks:
                ids = re.findall(r"^(v_\w+) \(", block, re.MULTILINE)
                ratings.append(CandidateRating(
                    node_id=block.split()[0], reason="Fake\nreason.",
                    plausible=self.pre_score * 10, relevant=self.pre_score * 10,
                    novel=self.pre_score * 10,
                    vault_items_used=[*ids[:1], "v_notshown"]))
            value = PreScoreBatch(ratings=ratings)
        elif schema is ObjectiveDraft:
            value = ObjectiveDraft(objectives=list(self.objectives))
        elif schema is PostScoreOutput:
            ids = re.findall(r"^(v_\w+) \(", prompt, re.MULTILINE)
            value = PostScoreOutput(reason="Fake\nreason.", post_score=self.post_score * 10,
                                    criteria_progress=[*self.progress, "c_bogus"],
                                    vault_items_used=[*ids[:1], "v_notshown"])
        else:
            raise AssertionError(f"unexpected schema {schema}")
        return Generated(value, TokenCount(input=10, output=5, calls=1), cached=False)

    async def embed(self, texts: list[str], **_: Any) -> list[list[float]]:
        return [bag_of_words(t) for t in texts]


class FakeGenaiClient:
    """Mimics the parts of google.genai.Client that pruner.llm uses."""

    def __init__(self, replies: list[str] | None = None) -> None:
        self.replies = list(replies or [])
        self.generate_calls = 0
        self.embed_calls: list[list[str]] = []
        self.aio = SimpleNamespace(models=SimpleNamespace(
            generate_content=self._generate, embed_content=self._embed))

    async def _generate(self, **_: Any) -> Any:
        self.generate_calls += 1
        usage = SimpleNamespace(prompt_token_count=100, candidates_token_count=20,
                                thoughts_token_count=None)
        return SimpleNamespace(text=self.replies.pop(0), usage_metadata=usage)

    async def _embed(self, *, contents: list[str], **_: Any) -> Any:
        self.embed_calls.append(list(contents))
        return SimpleNamespace(embeddings=[SimpleNamespace(values=bag_of_words(t))
                                           for t in contents])
