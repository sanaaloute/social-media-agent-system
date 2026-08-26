"""Web research for the Researcher Agent (§3.2).

Keyless hot-topic discovery via Google News RSS — no API key required, so
it works out of the box alongside the local Ollama LLM. Network failures
are the caller's problem (the researcher falls back to deterministic
defaults), keeping the pipeline alive offline.
"""
import logging
import xml.etree.ElementTree as ET
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
_TIMEOUT = 15.0
_MAX_QUERIES = 4


def search_hot_topics(
    queries: list[str], limit_per_query: int = 5, language: str = "en-US"
) -> list[dict]:
    """Recent news items for the given queries, newest first.

    Returns dicts: {title, link, published, source, query}. Duplicates
    (same story surfacing for several queries) are removed by title.
    Raises httpx.HTTPError on network/API failure.
    """
    items: list[dict] = []
    seen: set[str] = set()
    for query in [q.strip() for q in queries if q and q.strip()][:_MAX_QUERIES]:
        resp = httpx.get(
            GOOGLE_NEWS_RSS,
            params={"q": query, "hl": language, "gl": "US", "ceid": "US:en"},
            headers={"User-Agent": "Mozilla/5.0 (compatible; SocialAgent/1.0)"},
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        count = 0
        for node in root.iter("item"):
            title = (node.findtext("title") or "").strip()
            if not title or title.lower() in seen:
                continue
            seen.add(title.lower())
            source_el: Optional[ET.Element] = node.find("source")
            items.append(
                {
                    "title": title,
                    "link": node.findtext("link") or "",
                    "published": node.findtext("pubDate") or "",
                    "source": source_el.text if source_el is not None else "",
                    "query": query,
                }
            )
            count += 1
            if count >= limit_per_query:
                break
    logger.info("web research: %d items for queries %s", len(items), queries[:_MAX_QUERIES])
    return items
