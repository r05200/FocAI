"""Paper links: ingesting a vault item whose text is just a link (no file upload).

link_of(text) says whether an ingest request is a link. fetch_paper() reads the page (public
http(s) pages only, cached: agent/web.py PageFetcher) and returns its text for the ingest LLM
(prompts/vault_ingest_link.md), which pulls out the abstract, or the nearest thing to one, from
the page's own words. When the page cannot be read (unreachable, an error status, a PDF file, no
text) `problem` says why and the item is filed with the summary "No summary found (...)".

An arXiv PDF link (arxiv.org/pdf/<id>) is read from its abstract page (arxiv.org/abs/<id>)
instead, since PDFs are not parsed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pruner.agent.web import FetchError, PageFetcher

NO_SUMMARY = "No summary found"
_LINK = re.compile(r"^<?(https?://[^\s<>]+?)>?[.,;]*$", re.IGNORECASE)
_ARXIV_PDF = re.compile(r"^(https?://(?:www\.)?arxiv\.org)/pdf/([^?#]+?)(?:\.pdf)?(?:[?#].*)?$",
                        re.IGNORECASE)


def link_of(text: str) -> str | None:
    """The URL if `text` is nothing but a link (optionally in <>, or with trailing punctuation)."""
    m = _LINK.match(text.strip())
    return m.group(1) if m else None


def readable_url(url: str) -> str:
    """The page to read for a link: an arXiv PDF becomes its abstract page."""
    m = _ARXIV_PDF.match(url)
    return f"{m.group(1)}/abs/{m.group(2)}" if m else url


@dataclass
class PaperPage:
    url: str  # the link as given
    title: str = ""
    text: str = ""
    problem: str = ""  # why there is no text to read, if there is none


async def fetch_paper(fetcher: PageFetcher, url: str) -> PaperPage:
    page = PaperPage(url=url)
    try:
        fetched = await fetcher.fetch(readable_url(url))
    except FetchError as e:
        page.problem = str(e)
        return page
    if not 200 <= fetched.status < 300:
        page.problem = f"the page returned HTTP {fetched.status}"
    elif fetched.text.lstrip().startswith("%PDF"):
        page.problem = "the link is a PDF file, which is not read"
    elif not fetched.text.strip():
        page.problem = "the page has no readable text"
    else:
        page.title, page.text = fetched.title, fetched.text
    return page
