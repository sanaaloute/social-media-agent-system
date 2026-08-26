"""Web research (RSS parsing) + brand-guided hot-topic discovery (§3.2)."""
import httpx
import pytest

from src.agents import researcher, web_research
from src.agents.researcher import researcher_agent

CANNED_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Robot Games electrify Beijing as humanoids race</title>
    <link>https://news.google.com/articles/1</link>
    <pubDate>Tue, 26 Aug 2026 08:00:00 GMT</pubDate>
    <source>TechDaily</source>
  </item>
  <item>
    <title>Robot Games electrify Beijing as humanoids race</title>
    <link>https://news.google.com/articles/1dup</link>
    <pubDate>Tue, 26 Aug 2026 08:05:00 GMT</pubDate>
    <source>MirrorNews</source>
  </item>
  <item>
    <title>New GPU benchmark crowns a surprise winner</title>
    <link>https://news.google.com/articles/2</link>
    <pubDate>Mon, 25 Aug 2026 18:30:00 GMT</pubDate>
    <source>SiliconWeek</source>
  </item>
</channel></rss>"""


class _FakeResp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        return None


def test_search_parses_and_dedupes(monkeypatch):
    monkeypatch.setattr(
        web_research.httpx, "get", lambda *a, **k: _FakeResp(CANNED_RSS)
    )
    items = web_research.search_hot_topics(["robotics"])
    assert len(items) == 2  # duplicate title removed
    assert items[0]["title"].startswith("Robot Games")
    assert items[0]["source"] == "TechDaily"
    assert items[1]["title"].startswith("New GPU")


def test_search_network_error_raises(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(web_research.httpx, "get", boom)
    with pytest.raises(httpx.HTTPError):
        web_research.search_hot_topics(["ai"])


def _patch_researcher_llm(monkeypatch):
    class _LLM:
        def complete_json(self, system, prompt):
            return {}

    monkeypatch.setattr(researcher, "get_llm_provider", lambda: _LLM())


def test_researcher_discovers_topic_from_niche(monkeypatch):
    """No topic + brand keywords -> freshest story becomes the task topic."""
    monkeypatch.setattr(
        researcher,
        "search_hot_topics",
        lambda queries, **k: [
            {"title": "Humanoid robots race at Beijing games", "link": "",
             "published": "", "source": "TechDaily", "query": queries[0]},
        ],
    )
    _patch_researcher_llm(monkeypatch)

    out = researcher_agent(
        {
            "topic": "",
            "brand_context": {"niche": "tech", "keywords": ["robotics", "AI"]},
        }
    )
    assert out["topic"] == "Humanoid robots race at Beijing games"
    assert "Robot" in out["research_results"]["topics"][0] or "robot" in out["research_results"]["topics"][0]
    assert "Fresh coverage" in out["research_results"]["summary"]


def test_researcher_explicit_topic_guides_search(monkeypatch):
    seen = {}

    def fake_search(queries, **k):
        seen["queries"] = queries
        return [{"title": "Topic-specific headline", "link": "", "published": "",
                 "source": "X", "query": queries[0]}]

    monkeypatch.setattr(researcher, "search_hot_topics", fake_search)
    _patch_researcher_llm(monkeypatch)

    out = researcher_agent({"topic": "robot olympics", "brand_context": {"niche": "tech"}})
    assert seen["queries"] == ["robot olympics"]
    assert out["topic"] == "robot olympics"  # explicit topic wins over headlines


def test_researcher_offline_falls_back(monkeypatch):
    def boom(queries, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(researcher, "search_hot_topics", boom)
    _patch_researcher_llm(monkeypatch)

    out = researcher_agent(
        {"topic": "", "brand_context": {"niche": "entertainment", "keywords": ["movies"]}}
    )
    assert out["topic"] == "movies"  # first keyword as the fallback subject
    assert "web research unavailable" in out["error"]
    assert out["research_results"]["topics"]  # deterministic defaults still produced


# ── Brand routes + topic-less task flow ────────────────────────────────


def test_brand_crud(client):
    resp = client.post(
        "/api/brands",
        json={"name": "Acme Tech", "niche": "tech",
              "keywords": ["AI", "robotics", "GPUs"]},
    )
    assert resp.status_code == 201, resp.text
    brand = resp.json()
    assert brand["keywords"] == ["AI", "robotics", "GPUs"]

    brands = client.get("/api/brands").json()
    assert len(brands) == 1

    assert client.delete(f"/api/brands/{brand['id']}").status_code == 200
    assert client.get("/api/brands").json() == []

    resp = client.post("/api/brands", json={"name": "", "niche": "tech"})
    assert resp.status_code == 400


def test_task_requires_topic_or_brand(client):
    resp = client.post(
        "/api/tasks",
        json={"platforms": ["twitter"], "content_type": "text"},
    )
    assert resp.status_code == 400
    assert "topic" in resp.json()["detail"].lower()

    resp = client.post(
        "/api/tasks",
        json={"platforms": ["twitter"], "brand_id": "no-such-brand"},
    )
    assert resp.status_code == 404


def test_topic_less_task_discovers_and_records_topic(client, session, monkeypatch):
    """Brand-guided task with no topic runs the full pipeline and the
    discovered topic is written back onto the task row."""
    monkeypatch.setattr(
        researcher,
        "search_hot_topics",
        lambda queries, **k: [
            {"title": "Humanoid robots race at Beijing games", "link": "",
             "published": "", "source": "TechDaily", "query": queries[0]},
        ],
    )
    brand = client.post(
        "/api/brands",
        json={"name": "Acme Tech", "niche": "tech", "keywords": ["robotics"]},
    ).json()
    resp = client.post(
        "/api/tasks",
        json={"brand_id": brand["id"], "platforms": ["twitter"],
              "content_type": "text"},
    )
    assert resp.status_code == 201, resp.text

    task = client.get(f"/api/tasks/{resp.json()['id']}").json()
    assert task["status"] == "generated"
    assert task["topic"] == "Humanoid robots race at Beijing games"

    from src.core.models import GeneratedContent
    from sqlmodel import select

    contents = session.exec(
        select(GeneratedContent).where(GeneratedContent.task_id == task["id"])
    ).all()
    assert len(contents) == 1
    assert contents[0].status == "review"
