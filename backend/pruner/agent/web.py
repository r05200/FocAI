"""Web research for the agent: search, fetch, and checking that cited findings are real.

- SearchProvider: the web search API. "brave" (BraveSearch) is built in; with none set,
  get_search_provider() returns NoSearchProvider, whose search() raises SearchNotConfigured.
  To add another, write a class with an
  async `search(query, k)` returning SearchHit objects, and return it from get_search_provider()
  for its name (cfg.search_provider, env PRUNER_SEARCH_PROVIDER; key in SEARCH_API_KEY).
  Gemini's own Google Search grounding is not an option on the free tier for the 3.x models
  (paid only; checked 2026-10-17 on ai.google.dev/gemini-api/docs/pricing).
- PageFetcher: GET a public http(s) page and return its cleaned text, cached on disk. It refuses
  hosts that resolve to private, loopback or link-local addresses, so the agent cannot reach the
  machine it runs on or the local network.
- verify_findings(): the deterministic check for web findings. Each claim carries a source URL and
  an excerpt; the check passes only if the page loads and really contains the excerpt.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import ClassVar, Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel

from pruner.core.config import Config, get_config
from pruner.core.llm import DiskCache

MAX_BYTES = 3_000_000  # pages larger than this are cut off while downloading


# --------------------------------------------------------------------------- search


class SearchHit(BaseModel):
    title: str
    url: str
    snippet: str


class SearchNotConfigured(RuntimeError):
    pass


class SearchProvider(Protocol):
    async def search(self, query: str, k: int) -> list[SearchHit]: ...


class NoSearchProvider:
    """Placeholder until a search API is added."""

    async def search(self, query: str, k: int) -> list[SearchHit]:
        raise SearchNotConfigured(
            "web search is not set up yet (set PRUNER_SEARCH_PROVIDER and add the provider in "
            "pruner/agent/web.py)")


class BraveSearch:
    """The Brave Search API (api.search.brave.com, key in SEARCH_API_KEY). Not yet checked
    against the live API: the request and response shapes follow Brave's documented web search
    endpoint."""

    URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None,
                 timeout_s: float = 15.0) -> None:
        if not api_key:
            raise SearchNotConfigured("PRUNER_SEARCH_PROVIDER is brave but SEARCH_API_KEY is "
                                      "empty")
        self._key, self._client, self._timeout = api_key, client, timeout_s

    async def search(self, query: str, k: int) -> list[SearchHit]:
        client = self._client or httpx.AsyncClient()
        try:
            resp = await client.get(self.URL, params={"q": query, "count": k},
                                    headers={"Accept": "application/json",
                                             "X-Subscription-Token": self._key},
                                    timeout=self._timeout)
            resp.raise_for_status()
            results = (resp.json().get("web") or {}).get("results") or []
        finally:
            if self._client is None:
                await client.aclose()
        return [SearchHit(title=_strip_tags(r.get("title", "")), url=r["url"],
                          snippet=_strip_tags(r.get("description", "")))
                for r in results[:k] if r.get("url")]


def _strip_tags(text: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", "", text).split())


def get_search_provider(cfg: Config | None = None) -> SearchProvider:
    cfg = cfg or get_config()
    name = cfg.search_provider.strip().lower()
    if not name:
        return NoSearchProvider()
    if name == "brave":
        return BraveSearch(cfg.search_api_key)
    raise SearchNotConfigured(f"unknown search provider {cfg.search_provider!r}")


# --------------------------------------------------------------------------- fetch


class Page(BaseModel):
    url: str
    status: int
    title: str = ""
    text: str = ""


class FetchError(RuntimeError):
    pass


class _TextExtractor(HTMLParser):
    SKIP: ClassVar[set[str]] = {"script", "style", "noscript", "svg", "template", "iframe", "head"}
    BLOCK: ClassVar[set[str]] = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section",
             "article", "header", "footer", "blockquote", "pre", "table", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: list[str] = []
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title.append(data)
        elif not self._skip:
            self.parts.append(re.sub(r"\s+", " ", data))  # source newlines are not breaks


def clean_html(html: str) -> tuple[str, str]:
    """(title, text): visible text only, one paragraph per line."""
    parser = _TextExtractor()
    parser.feed(html)
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return " ".join("".join(parser.title).split()), "\n".join(line for line in lines if line)


Resolver = Callable[[str], Awaitable[list[str]]]


async def _resolve(host: str) -> list[str]:
    infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    return [info[4][0] for info in infos]


async def check_public_url(url: str, resolve: Resolver = _resolve) -> None:
    """Raise FetchError unless `url` is http(s) and its host resolves only to public addresses."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("only http and https URLs can be fetched")
    try:
        addresses = await resolve(parts.hostname)
    except OSError as e:
        raise FetchError(f"could not resolve {parts.hostname}") from e
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if not ip.is_global:
            raise FetchError(f"{parts.hostname} is not a public address")


class PageFetcher:
    def __init__(self, cfg: Config | None = None, client: httpx.AsyncClient | None = None,
                 resolve: Resolver = _resolve) -> None:
        self.cfg = cfg or get_config()
        self._client = client
        self._resolve = resolve
        self.cache = DiskCache(self.cfg.cache_dir / "fetch")

    async def fetch(self, url: str) -> Page:
        key = DiskCache.key({"kind": "fetch", "url": url})
        if (hit := self.cache.get(key)) is not None:
            return Page.model_validate(hit)
        page = await self._download(url)
        if 200 <= page.status < 300:  # only good pages are cached, so failures are retried
            self.cache.set(key, page.model_dump())
        return page

    async def _download(self, url: str, hops: int = 5) -> Page:
        client = self._client or httpx.AsyncClient()
        try:
            for _ in range(hops):  # redirects are followed by hand so every hop is checked
                await check_public_url(url, self._resolve)
                async with client.stream("GET", url, timeout=self.cfg.fetch_timeout_s,
                                         headers={"user-agent": "pruner-research-agent"},
                                         follow_redirects=False) as resp:
                    if resp.is_redirect and "location" in resp.headers:
                        url = str(resp.url.join(resp.headers["location"]))
                        continue
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) >= MAX_BYTES:
                            break
                    text = body.decode(resp.encoding or "utf-8", errors="replace")
                    kind = resp.headers.get("content-type", "")
                    title, clean = clean_html(text) if "html" in kind or "<html" in text[:500] \
                        else ("", text)
                    # The full text is kept so verify_findings can find excerpts anywhere on the
                    # page; the fetch tool cuts what it shows the agent to cfg.fetch_max_chars.
                    return Page(url=url, status=resp.status_code, title=title, text=clean)
            raise FetchError("too many redirects")
        except httpx.HTTPError as e:
            raise FetchError(f"could not fetch {url}: {e.__class__.__name__}") from e
        finally:
            if self._client is None:
                await client.aclose()


# --------------------------------------------------------------------------- findings


class Finding(BaseModel):
    """One claim from web research, with where it came from."""

    claim: str
    url: str
    excerpt: str  # copied word for word from the page


@dataclass
class FindingCheck:
    finding: Finding
    ok: bool
    reason: str


_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                         "–": "-", "—": "-", " ": " "})


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_QUOTES)).strip().casefold()


async def verify_findings(findings: list[Finding], fetcher: PageFetcher) -> list[FindingCheck]:
    """Check every finding: its page must load (2xx) and contain its excerpt (ignoring case,
    spacing and curly quotes). Pages are fetched once each, through the cache."""
    pages: dict[str, Page | str] = {}
    for url in {f.url for f in findings}:
        try:
            pages[url] = await fetcher.fetch(url)
        except FetchError as e:
            pages[url] = str(e)
    checks = []
    for f in findings:
        page = pages[f.url]
        if isinstance(page, str):
            checks.append(FindingCheck(f, False, page))
        elif not 200 <= page.status < 300:
            checks.append(FindingCheck(f, False, f"page returned {page.status}"))
        elif len(_normalize(f.excerpt)) < 12:
            checks.append(FindingCheck(f, False, "excerpt is too short to check"))
        elif _normalize(f.excerpt) not in _normalize(f"{page.title} {page.text}"):
            checks.append(FindingCheck(f, False, "the page does not contain the excerpt"))
        else:
            checks.append(FindingCheck(f, True, "ok"))
    return checks
