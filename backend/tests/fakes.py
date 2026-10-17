"""Test doubles: no network, deterministic."""

from __future__ import annotations

import hashlib
import re
from types import SimpleNamespace
from typing import Any

import numpy as np

from pruner.llm import Generated, TokenCount
from pruner.vault import IngestDraft, RelationJudgement, RelationOutput

DIM = 64


def bag_of_words(text: str, dim: int = DIM) -> list[float]:
    """Hashed word counts: texts sharing words get high cosine similarity."""
    v = np.zeros(dim)
    for word in re.findall(r"[a-z]+", text.lower()):
        v[int(hashlib.md5(word.encode()).hexdigest(), 16) % dim] += 1
    return v.tolist()


class FakeLLM:
    """Stands in for pruner.llm.LLM inside VaultStore."""

    def __init__(self, relation: str = "supports") -> None:
        self.relation = relation
        self.prompts: list[str] = []

    async def generate(self, schema: Any, prompt: str, **_: Any) -> Generated:
        self.prompts.append(prompt)
        if schema is IngestDraft:
            text = prompt.split('"""')[1].strip()
            words = text.split()
            value = IngestDraft(title=" ".join(words[:5]), summary=text[:80],
                                tags=["Long Context", "kv cache", "long-context"])
        elif schema is RelationOutput:
            ids = re.findall(r"neighbor_id: (\S+)", prompt)
            value = RelationOutput(relations=[
                RelationJudgement(neighbor_id=i, relation=self.relation,
                                  reason="Fake reason\nspanning lines.") for i in ids])
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
