"""The only module that talks to an LLM provider (Gemini today).

- generate(): structured output. The pydantic schema is sent as the response JSON schema and the
  reply is validated against it, with one corrective retry if it does not validate.
- embed(): batched embeddings, truncated to cfg.embedding_dim.
- Every call is cached on disk, keyed by everything that affects the output, so demo reruns are
  instant and deterministic. Cache hits still report the tokens the original call cost, so cost
  comparisons are the same whether or not the cache was warm.
- Token usage is accumulated per `purpose` (e.g. "vault_ingest", "scorer") in self.usage.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from pruner.core.config import Config, get_config

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_API_ATTEMPTS = 3


class LLMError(RuntimeError):
    pass


class TokenCount(BaseModel):
    input: int = 0
    output: int = 0
    calls: int = 0

    @property
    def total(self) -> int:
        return self.input + self.output

    def add(self, other: TokenCount) -> None:
        self.input += other.input
        self.output += other.output
        self.calls += other.calls


@dataclass
class Generated(Generic[T]):
    value: T
    tokens: TokenCount
    cached: bool


class DiskCache:
    def __init__(self, directory: Path) -> None:
        self.dir = directory

    @staticmethod
    def key(payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _path(self, key: str) -> Path:
        return self.dir / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        return json.loads(path.read_text()) if path.exists() else None

    def set(self, key: str, value: dict[str, Any]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value))
        tmp.replace(path)


class LLM:
    def __init__(self, cfg: Config | None = None, client: Any = None,
                 cache_dir: Path | None = None) -> None:
        self.cfg = cfg or get_config()
        self._client = client  # a google.genai.Client, or a stand-in in tests
        self.cache = DiskCache(cache_dir or self.cfg.cache_dir / "llm")
        self.usage: dict[str, TokenCount] = {}

    @property
    def client(self) -> Any:
        if self._client is None:
            if not self.cfg.gemini_api_key:
                raise LLMError("GEMINI_API_KEY is not set (see .env.example)")
            from google import genai

            self._client = genai.Client(api_key=self.cfg.gemini_api_key)
        return self._client

    def _record(self, purpose: str, tokens: TokenCount) -> None:
        self.usage.setdefault(purpose, TokenCount()).add(tokens)

    async def _call_api(self, fn: Any, **kwargs: Any) -> Any:
        from google.genai import errors

        for attempt in range(MAX_API_ATTEMPTS):
            try:
                return await fn(**kwargs)
            except errors.APIError as e:
                if e.code not in RETRYABLE_STATUS or attempt == MAX_API_ATTEMPTS - 1:
                    raise LLMError(f"Gemini API error {e.code}: {e.message}") from e
                delay = 2**attempt
                log.warning("Gemini API error %s, retrying in %ss", e.code, delay)
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def generate(self, schema: type[T], prompt: str, *, model: str, purpose: str,
                       system: str | None = None) -> Generated[T]:
        json_schema = schema.model_json_schema()
        key = DiskCache.key({
            "kind": "generate", "model": model, "system": system, "prompt": prompt,
            "schema": json_schema, "temperature": self.cfg.temperature,
        })
        if (hit := self.cache.get(key)) is not None:
            tokens = TokenCount.model_validate(hit["tokens"])
            self._record(purpose, tokens)
            return Generated(schema.model_validate_json(hit["text"]), tokens, cached=True)

        tokens = TokenCount()
        contents = prompt
        last_error: Exception | None = None
        from google.genai import types

        for _ in range(2):  # one corrective retry on invalid output
            resp = await self._call_api(
                self.client.aio.models.generate_content,
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=self.cfg.temperature,
                    response_mime_type="application/json",
                    response_json_schema=json_schema,
                ),
            )
            usage = resp.usage_metadata
            tokens.add(TokenCount(
                input=(usage.prompt_token_count or 0) if usage else 0,
                output=((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0))
                if usage else 0,
                calls=1,
            ))
            text = resp.text or ""
            try:
                value = schema.model_validate_json(text)
            except ValidationError as e:
                last_error = e
                log.warning("invalid structured output for %s, retrying: %s", purpose, e)
                contents = (f"{prompt}\n\nYour previous reply did not match the required JSON "
                            f"schema ({e.error_count()} errors). Reply with valid JSON only.")
                continue
            self.cache.set(key, {"text": text, "tokens": tokens.model_dump()})
            self._record(purpose, tokens)
            return Generated(value, tokens, cached=False)

        self._record(purpose, tokens)
        raise LLMError(f"{purpose}: model output did not match {schema.__name__}: {last_error}")

    async def embed(self, texts: list[str], *, task: str = "RETRIEVAL_DOCUMENT",
                    purpose: str = "embed") -> list[list[float]]:
        model, dim = self.cfg.embedding_model, self.cfg.embedding_dim
        keys = [DiskCache.key({"kind": "embed", "model": model, "dim": dim, "task": task,
                               "text": t}) for t in texts]
        out: list[list[float] | None] = [None] * len(texts)
        missing: list[int] = []
        for i, key in enumerate(keys):
            hit = self.cache.get(key)
            if hit is None:
                missing.append(i)
            else:
                out[i] = hit["values"]

        if missing:
            from google.genai import types

            resp = await self._call_api(
                self.client.aio.models.embed_content,
                model=model,
                contents=[texts[i] for i in missing],
                config=types.EmbedContentConfig(task_type=task, output_dimensionality=dim),
            )
            if len(resp.embeddings) != len(missing):
                raise LLMError(f"asked for {len(missing)} embeddings, got {len(resp.embeddings)}")
            for i, emb in zip(missing, resp.embeddings, strict=True):
                out[i] = list(emb.values)
                self.cache.set(keys[i], {"values": out[i]})
            self._record(purpose, TokenCount(calls=1))  # the API reports no token counts here

        return out  # type: ignore[return-value]
