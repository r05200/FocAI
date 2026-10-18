"""The only module that talks to an LLM provider (Gemini today).

- generate(): structured output. The pydantic schema is sent as the response JSON schema and the
  reply is validated against it, with one corrective retry if it does not validate.
- embed(): batched embeddings, truncated to cfg.embedding_dim.
- Every call is cached on disk, keyed by everything that affects the output, so demo reruns are
  instant and deterministic. Cache hits still report the tokens the original call cost, so cost
  comparisons are the same whether or not the cache was warm.
- Token usage is accumulated per `purpose` (e.g. "vault_ingest", "scorer") in self.usage.
- run_tools(): Gemini function calling. A manual loop (so every API call still goes through
  _call_api: retries, scope/stop): the model may call the given tools; each turn's calls are
  answered with their results in one reply; once max_calls is used up the tools are switched off
  (mode NONE) so the model has to answer. The model's turns are echoed back unchanged, which keeps
  Gemini 3.x thought signatures intact. Each step is cached on disk under a key that includes the
  whole conversation so far (tool results included), so a re-run is a chain of cache hits and
  diverges exactly where a tool returned something different.
- stop(): cancels calls that are in flight. Every API call runs as its own asyncio task that is
  tracked with the scope it was started in, so stopping cancels the task (and with it the HTTP
  request) and the caller gets LLMCancelled. Calls are scoped with `with llm.scope(run_id):`;
  stopping a scope also refuses its later calls, so an agent loop cannot start the next step.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from pruner.core.config import Config, get_config
from pruner.core.fs import write_atomic

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_API_ATTEMPTS = 3


Role = Literal["agent", "supporting"]


class LLMError(RuntimeError):
    pass


class LLMCancelled(LLMError):
    """The call was stopped by LLM.stop() before it finished."""


_scope: ContextVar[str | None] = ContextVar("llm_scope", default=None)


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


ToolHandler = Callable[[str, dict[str, Any]], Awaitable[str]]
TOOL_RESULT_MAX_CHARS = 6000  # a tool's answer is cut to this before it goes back to the model
TOOL_BUDGET_EXHAUSTED = json.dumps({"error": "tool budget exhausted; answer now"})


@dataclass
class ToolTranscript:
    """What happened in a run_tools() conversation."""

    final_text: str  # the text of the turn that called no tool
    thoughts: list[str]  # thought summaries the model returned, if any
    calls: list[tuple[str, dict[str, Any], str]]  # (tool, args, result) in order
    tokens: TokenCount
    api_calls: int  # calls that reached the API (cache hits excluded)
    cached_steps: int

    def evidence(self) -> str:
        """The tool calls and their results as plain text, for a follow-up prompt."""
        if not self.calls:
            return "(no tools were called)"
        return "\n\n".join(f"{name}({json.dumps(args, ensure_ascii=False)}) ->\n{result}"
                            for name, args, result in self.calls)


def _tokens_of(resp: Any) -> TokenCount:
    usage = getattr(resp, "usage_metadata", None)
    return TokenCount(
        input=(usage.prompt_token_count or 0) if usage else 0,
        output=((usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0))
        if usage else 0,
        calls=1,
    )


def _retry_delay(error: Any, attempt: int) -> float:
    """How long to wait before retrying: the API's own retryDelay on a 429 when it gives one
    (capped at a minute), otherwise 1, 2, 4... seconds."""
    details = getattr(error, "details", None) or getattr(error, "response_json", None)
    match = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", str(details or ""))
    if getattr(error, "code", None) == 429 and match:
        return min(float(match.group(1)), 60.0)
    return float(2**attempt)


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
        write_atomic(self._path(key), json.dumps(value))


class LLM:
    def __init__(self, cfg: Config | None = None, client: Any = None,
                 cache_dir: Path | None = None, role: Role = "supporting") -> None:
        self.cfg = cfg or get_config()
        self.role = role  # picks the API key: GEMINI_API_KEY_AGENT or GEMINI_API_KEY_SUPPORTING
        self._client = client  # a google.genai.Client, or a stand-in in tests
        self.cache = DiskCache(cache_dir or self.cfg.cache_dir / "llm")
        self.usage: dict[str, TokenCount] = {}
        self._inflight: dict[asyncio.Future, str | None] = {}  # running API call -> its scope
        self._stopping: set[asyncio.Future] = set()  # calls cancelled by stop(), not by a caller
        self._stopped: set[str] = set()  # scopes that were stopped
        self._last_call = 0.0  # monotonic time of the last API call (free-tier pacing)
        self._pace = asyncio.Lock()
        self._key_gen = 0  # bumped when a 429 switches this LLM to its backup key

    @contextmanager
    def scope(self, name: str) -> Iterator[None]:
        """Tag every call made inside the block (including in tasks it starts) with `name`,
        usually a run id, so stop(name) can cancel just those."""
        token = _scope.set(name)
        try:
            yield
        finally:
            _scope.reset(token)

    def stop(self, scope: str | None = None) -> int:
        """Cancel the calls in flight: only those in `scope`, or every call if it is None.
        A named scope is also marked stopped, so its later calls raise LLMCancelled at once.
        Returns how many in-flight calls were cancelled."""
        if scope is not None:
            self._stopped.add(scope)
        targets = [t for t, s in self._inflight.items() if scope is None or s == scope]
        for task in targets:
            self._stopping.add(task)
            task.cancel()
        return len(targets)

    def is_stopped(self, scope: str) -> bool:
        return scope in self._stopped

    @property
    def client(self) -> Any:
        if self._client is None:
            env = f"GEMINI_API_KEY_{self.role.upper()}"
            key = getattr(self.cfg, f"gemini_api_key_{self.role}")
            if not key:
                raise LLMError(f"{env} is not set (see .env.example)")
            self._client = self._make_client(key)
        return self._client

    def _make_client(self, key: str) -> Any:
        from google import genai
        from google.genai import types

        return genai.Client(api_key=key, http_options=types.HttpOptions(
            timeout=int(self.cfg.llm_timeout_s * 1000)))  # milliseconds

    def _switch_to_backup_key(self) -> bool:
        """After a 429: move this LLM to its backup key (GEMINI_API_KEY_<ROLE>_2) for good, if one
        is set and not already in use. Quiet: it is only logged, never shown to the user."""
        backup = getattr(self.cfg, f"gemini_api_key_{self.role}_2", "")
        if not backup or self._key_gen > 0:
            return False
        self._client = self._make_client(backup)
        self._key_gen += 1
        log.warning("Gemini %s key hit a 429; switched to GEMINI_API_KEY_%s_2 and resuming",
                    self.role, self.role.upper())
        return True

    def _record(self, purpose: str, tokens: TokenCount) -> None:
        self.usage.setdefault(purpose, TokenCount()).add(tokens)

    async def _wait_turn(self) -> None:
        """Keep at least cfg.llm_min_interval_s between two API calls on this key."""
        gap = self.cfg.llm_min_interval_s
        if gap <= 0:
            return
        async with self._pace:
            wait = self._last_call + gap - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()

    async def _call_api(self, method: str, **kwargs: Any) -> Any:
        """Call client.aio.models.<method>. It is looked up on the current client at every
        attempt, so a switch to the backup key takes effect for the redone call."""
        from google.genai import errors

        scope = _scope.get()
        attempt = 0
        while True:
            if scope in self._stopped:
                raise LLMCancelled(f"scope {scope!r} was stopped")
            await self._wait_turn()
            if scope in self._stopped:
                raise LLMCancelled(f"scope {scope!r} was stopped")
            gen = self._key_gen
            task = asyncio.ensure_future(getattr(self.client.aio.models, method)(**kwargs))
            self._inflight[task] = scope
            try:
                return await task
            except asyncio.CancelledError:
                me = asyncio.current_task()
                if task in self._stopping and not (me is not None and me.cancelling()):
                    raise LLMCancelled("the call was stopped") from None
                task.cancel()  # the caller itself was cancelled: do not leave the request running
                raise
            except errors.APIError as e:
                if e.code == 429 and (self._key_gen != gen or self._switch_to_backup_key()):
                    # Freeze this call and redo it on the backup key: no wait, no attempt used
                    # (also when another call already made the switch while this one was in flight).
                    continue
                if e.code not in RETRYABLE_STATUS or attempt == MAX_API_ATTEMPTS - 1:
                    log.error("500 server issue: the Gemini %s API call failed (HTTP %s: %s). If "
                              "this keeps happening, change GEMINI_API_KEY_%s in .env.",
                              self.role.upper(), e.code, e.message, self.role.upper())
                    raise LLMError(f"Gemini API error {e.code}: {e.message}") from e
                delay = _retry_delay(e, attempt)
                log.warning("Gemini API error %s, retrying in %ss", e.code, delay)
                await asyncio.sleep(delay)
                attempt += 1
            except (httpx.TransportError, TimeoutError) as e:  # a dropped or stalled connection
                if attempt == MAX_API_ATTEMPTS - 1:
                    log.error("the Gemini %s API could not be reached (%s: %s)",
                              self.role, type(e).__name__, e)
                    raise LLMError(f"Gemini API unreachable: {type(e).__name__}: {e}") from e
                delay = _retry_delay(None, attempt)
                log.warning("Gemini API unreachable (%s), retrying in %ss", type(e).__name__,
                            delay)
                await asyncio.sleep(delay)
                attempt += 1
            finally:
                self._inflight.pop(task, None)
                self._stopping.discard(task)

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
                "generate_content",
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

    async def run_tools(self, prompt: str, tools: list[dict[str, Any]], handler: ToolHandler, *,
                        model: str, purpose: str, system: str | None = None,
                        max_calls: int = 3, response_schema: dict[str, Any] | None = None,
                        ) -> ToolTranscript:
        """Let the model call `tools` (each a dict with name, description and a JSON-schema
        `parameters`) until it answers in text. `handler(name, args)` runs a call and returns its
        result as text; it is called at most `max_calls` times, later calls get an error. With
        `response_schema`, the final answer is also asked for as JSON of that schema."""
        from google.genai import types

        declarations = [types.FunctionDeclaration(name=t["name"], description=t["description"],
                                                  parameters_json_schema=t["parameters"])
                        for t in tools]
        contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]
        out = ToolTranscript(final_text="", thoughts=[], calls=[], tokens=TokenCount(),
                             api_calls=0, cached_steps=0)
        used = 0
        for _ in range(max_calls + 2):  # every step but the last may call tools
            mode = "NONE" if used >= max_calls else "AUTO"
            key = DiskCache.key({
                "kind": "tools_step", "model": model, "system": system, "mode": mode,
                "temperature": self.cfg.temperature, "tools": tools,
                "schema": response_schema,
                "contents": [c.model_dump(mode="json", exclude_none=True) for c in contents],
            })
            if (hit := self.cache.get(key)) is not None:
                content = types.Content.model_validate(hit["content"])
                tokens = TokenCount.model_validate(hit["tokens"])
                out.cached_steps += 1
            else:
                config = types.GenerateContentConfig(
                    system_instruction=system, temperature=self.cfg.temperature,
                    tools=[types.Tool(function_declarations=declarations)],
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(mode=mode)),
                    **({"response_mime_type": "application/json",
                        "response_json_schema": response_schema} if response_schema else {}))
                resp = await self._call_api("generate_content",
                                            model=model, contents=contents, config=config)
                if not resp.candidates or resp.candidates[0].content is None:
                    reason = (resp.candidates[0].finish_reason if resp.candidates else
                              "no candidates")
                    log.warning("%s: the model returned no content (%s); treating it as an "
                                "empty answer", purpose, reason)
                    content = types.Content(role="model", parts=[])
                else:
                    content = resp.candidates[0].content
                tokens = _tokens_of(resp)
                out.api_calls += 1
                self.cache.set(key, {"content": content.model_dump(mode="json", exclude_none=True),
                                     "tokens": tokens.model_dump()})
            out.tokens.add(tokens)
            contents.append(content)  # unchanged: keeps the thought signatures
            parts = content.parts or []
            out.thoughts += [p.text for p in parts if p.thought and p.text]
            calls = [p.function_call for p in parts if p.function_call]
            if not calls:
                out.final_text = "".join(p.text for p in parts if p.text and not p.thought)
                self._record(purpose, out.tokens)
                return out
            replies = []
            for call in calls:
                args = dict(call.args or {})
                if used < max_calls:
                    used += 1
                    result = await handler(call.name or "", args)
                else:
                    result = TOOL_BUDGET_EXHAUSTED
                out.calls.append((call.name or "", args, result))
                replies.append(types.Part(function_response=types.FunctionResponse(
                    id=call.id, name=call.name,
                    response={"output": result[:TOOL_RESULT_MAX_CHARS]})))
            contents.append(types.Content(role="user", parts=replies))
        self._record(purpose, out.tokens)
        raise LLMError(f"{purpose}: the model kept calling tools after they were switched off")

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
                "embed_content",
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
