import pytest
from pydantic import BaseModel

from pruner.core.llm import LLM, LLMError
from tests.fakes import FakeGenaiClient


class Answer(BaseModel):
    word: str


def make(cfg, replies=None):
    client = FakeGenaiClient(replies)
    return LLM(cfg, client=client), client


async def test_generate_parses_and_counts_tokens(cfg):
    llm, _ = make(cfg, ['{"word": "hi"}'])
    out = await llm.generate(Answer, "say hi", model="m", purpose="test")
    assert out.value.word == "hi" and not out.cached
    assert (out.tokens.input, out.tokens.output, out.tokens.calls) == (100, 20, 1)
    assert llm.usage["test"].total == 120


async def test_cache_hit_skips_api_but_still_reports_tokens(cfg):
    llm, client = make(cfg, ['{"word": "hi"}'])
    await llm.generate(Answer, "say hi", model="m", purpose="test")
    again = await LLM(cfg, client=client).generate(Answer, "say hi", model="m", purpose="test")
    assert client.generate_calls == 1
    assert again.cached and again.value.word == "hi" and again.tokens.total == 120


async def test_cache_key_includes_prompt_and_model(cfg):
    llm, client = make(cfg, ['{"word": "a"}', '{"word": "b"}', '{"word": "c"}'])
    await llm.generate(Answer, "p1", model="m", purpose="t")
    await llm.generate(Answer, "p2", model="m", purpose="t")
    await llm.generate(Answer, "p1", model="other", purpose="t")
    assert client.generate_calls == 3


async def test_invalid_output_is_retried_once(cfg):
    llm, client = make(cfg, ["not json", '{"word": "ok"}'])
    out = await llm.generate(Answer, "p", model="m", purpose="t")
    assert out.value.word == "ok" and client.generate_calls == 2
    assert out.tokens.calls == 2  # the failed attempt still cost tokens


async def test_twice_invalid_output_raises(cfg):
    llm, _ = make(cfg, ['{"nope": 1}', '{"nope": 2}'])
    with pytest.raises(LLMError):
        await llm.generate(Answer, "p", model="m", purpose="t")
    assert llm.usage["t"].calls == 2


async def test_embed_only_requests_uncached_texts(cfg):
    llm, client = make(cfg)
    first = await llm.embed(["alpha", "beta"])
    second = await llm.embed(["beta", "gamma", "alpha"])
    assert client.embed_calls == [["alpha", "beta"], ["gamma"]]
    assert second[0] == first[1] and second[2] == first[0]


async def test_missing_api_key_is_a_clear_error(cfg):
    import dataclasses

    llm = LLM(dataclasses.replace(cfg, gemini_api_key=""))
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        await llm.generate(Answer, "p", model="m", purpose="t")
