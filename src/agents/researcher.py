"""Researcher Agent: discovers hot topics and turns them into a TrendReport (§3.2).

Two modes:
- **Guided** (task has a topic): fresh coverage of that topic enriches the report.
- **Discovery** (no topic): the brand's niche/keywords drive a web search for
  hot topics (Google News RSS via `web_research`), the freshest story becomes
  the task's topic, and downstream agents (planner/writer) inherit it via
  the returned state update.

Web failures never kill the pipeline — the agent falls back to its
deterministic defaults and records the error in state.
"""
import logging

import httpx

from src.agents.memory import recall
from src.agents.providers import get_llm_provider, merge_llm_schema
from src.agents.state import AgentState
from src.agents.web_research import search_hot_topics
from src.core.models.schemas import TrendReport

logger = logging.getLogger(__name__)


def researcher_agent(state: AgentState) -> dict:
    topic = (state.get("topic") or "").strip()
    brand = state.get("brand_context") or {}
    niche = (brand.get("niche") or "").strip()
    keywords = [k for k in (brand.get("keywords") or []) if k.strip()]

    # What to search: the explicit topic, else the brand's keywords/niche.
    queries = [topic] if topic else (keywords or ([niche] if niche else []))
    news: list[dict] = []
    news_error = None
    if queries:
        try:
            news = search_hot_topics(queries)
        except httpx.HTTPError as exc:
            logger.warning("web research unavailable: %s", exc)
            news_error = f"web research unavailable: {exc}"

    # Memory: don't resurface topics this brand already covered recently.
    brand_id = brand.get("brand_id") or ""
    if news and brand_id:
        covered = {
            t.lower()
            for t in recall(brand_id, "covered_topic", limit=50, since_days=30)
            if len(t) > 15
        }
        if covered:
            fresh = [
                item
                for item in news
                if not any(
                    c in item["title"].lower() or item["title"].lower() in c
                    for c in covered
                )
            ]
            if fresh:
                news = fresh

    # The subject every downstream agent writes about.
    chosen_topic = topic or (
        news[0]["title"]
        if news
        else (keywords[0] if keywords else (niche or "trending topics"))
    )

    if news:
        headlines = [item["title"] for item in news[:6]]
        first = news[0]
        summary = (
            f"Fresh coverage: '{first['title']}'"
            + (f" ({first['source']})" if first.get("source") else "")
            + f" — plus {len(news) - 1} related stories."
        )
        hashtag_seed = niche or chosen_topic
    else:
        headlines = [chosen_topic, f"{chosen_topic} trends", f"{chosen_topic} tips"]
        summary = (
            f"Audience interest in '{chosen_topic}' is steady; practical, "
            "visual content performs best right now."
        )
        hashtag_seed = niche or chosen_topic

    slug = "#" + "".join(hashtag_seed.lower().split())[:20]
    defaults = {
        "topics": headlines,
        "hashtags": [slug, "#trending", "#news"],
        "summary": summary,
    }

    news_block = "\n".join(
        f"- {item['title']}"
        + (f" [{item['source']}]" if item.get("source") else "")
        for item in news[:10]
    ) or "(no fresh news retrieved)"
    llm = get_llm_provider()
    report = merge_llm_schema(
        TrendReport,
        defaults,
        llm.complete_json(
            system="You are a social-media trend researcher.",
            prompt=(
                f"Niche: {niche or 'general'}.\n"
                f"Subject: {chosen_topic}.\n"
                f"Fresh headlines from the web:\n{news_block}\n\n"
                "Pick the angles most likely to perform well on social media "
                "in this niche. "
                'Return JSON like {"topics": ["..."], "hashtags": ["#..."], '
                '"summary": "..."}.'
            ),
        ),
    )

    update = {
        "research_results": report.model_dump(),
        "topic": chosen_topic,  # inherited by planner/writer when discovering
        "status": "researched",
    }
    if news_error:
        update["error"] = news_error
    return update
