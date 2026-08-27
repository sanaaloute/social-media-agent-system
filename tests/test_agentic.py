"""Agentic hardening: memory, retry, LLM fallback, reflection inputs,
node logging, and the autopilot mode (§3.2, §6, §8).
"""
import httpx
import pytest

from src.agents import providers, researcher, writer
from src.agents.memory import recall, remember
from src.agents.providers import FallbackLLM, LLMProvider, _with_retry
from src.core.models import Brand


# ── memory ─────────────────────────────────────────────────────────────


def test_memory_roundtrip():
    remember("b-mem", "covered_topic", "AI robots invade the olympics")
    remember("b-mem", "covered_topic", "GPUs get cheaper")
    remember("b-mem", "review_feedback", "less hype please")
    remember("other-brand", "covered_topic", "unrelated")

    topics = recall("b-mem", "covered_topic")
    assert topics[0] == "GPUs get cheaper"  # newest first
    assert len(topics) == 2
    assert recall("b-mem", "review_feedback") == ["less hype please"]
    assert recall("b-mem", "covered_topic", since_days=30) == topics


def test_researcher_skips_covered_topics(monkeypatch):
    remember("b-skip", "covered_topic", "Humanoid robots race at Beijing games")

    monkeypatch.setattr(
        researcher,
        "search_hot_topics",
        lambda queries, **k: [
            {"title": "Humanoid robots race at Beijing games", "link": "",
             "published": "", "source": "A", "query": "robotics"},
            {"title": "New GPU benchmark crowns surprise winner", "link": "",
             "published": "", "source": "B", "query": "robotics"},
        ],
    )

    class _LLM:
        def complete_json(self, system, prompt):
            return {}

    monkeypatch.setattr(researcher, "get_llm_provider", lambda: _LLM())
    out = researcher.researcher_agent(
        {"topic": "", "brand_context": {"brand_id": "b-skip", "niche": "tech",
                                        "keywords": ["robotics"]}}
    )
    assert out["topic"] == "New GPU benchmark crowns surprise winner"


def test_reject_feedback_flows_into_writer_prompt(client, session, monkeypatch):
    """Reviewer's reject feedback lands in memory and reaches the writer."""
    from src.core.models import ContentTask, GeneratedContent
    from src.services import approval_service

    task = ContentTask(brand_id="", platforms=["twitter"], topic="t")
    session.add(task)
    session.commit()
    # brand via task; use a brand row so memory has a brand_id
    brand = Brand(name="B", niche="tech", keywords=["ai"])
    session.add(brand)
    session.commit()
    task.brand_id = brand.id
    session.add(task)
    content = GeneratedContent(task_id=task.id, platform="twitter", text="x",
                               status="review")
    session.add(content)
    session.commit()

    approval_service.reject(session, content.id, "carol", "too corporate, be casual")
    assert recall(brand.id, "review_feedback") == ["too corporate, be casual"]

    prompts = []

    class _LLM:
        def complete_json(self, system, prompt):
            prompts.append(prompt)
            return {}

    monkeypatch.setattr(writer, "get_llm_provider", lambda: _LLM())
    writer.writer_agent(
        {
            "topic": "launch",
            "platforms": ["twitter"],
            "brand_context": {"brand_id": brand.id, "niche": "tech"},
            "content_plan": {},
            "research_results": {},
        }
    )
    assert any("too corporate, be casual" in p for p in prompts)


# ── retry ──────────────────────────────────────────────────────────────


def test_retry_succeeds_after_transient_failure(monkeypatch):
    monkeypatch.setattr(providers.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("boom")
        return "ok"

    assert _with_retry(flaky) == "ok"
    assert calls["n"] == 3


def test_retry_does_not_retry_4xx(monkeypatch):
    monkeypatch.setattr(providers.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def bad_request():
        calls["n"] += 1
        request = httpx.Request("POST", "http://x")
        response = httpx.Response(400, request=request)
        raise httpx.HTTPStatusError("bad", request=request, response=response)

    with pytest.raises(httpx.HTTPStatusError):
        _with_retry(bad_request)
    assert calls["n"] == 1


def test_retry_gives_up_after_attempts(monkeypatch):
    monkeypatch.setattr(providers.time, "sleep", lambda s: None)

    def always_down():
        raise httpx.ConnectError("down")

    with pytest.raises(httpx.ConnectError):
        _with_retry(always_down, attempts=2)


# ── LLM fallback ───────────────────────────────────────────────────────


class _DeadLLM(LLMProvider):
    def complete(self, system, prompt):
        raise RuntimeError("provider down")

    def complete_json(self, system, prompt):
        raise RuntimeError("provider down")


class _AliveLLM(LLMProvider):
    def complete(self, system, prompt):
        return "fallback-text"

    def complete_json(self, system, prompt):
        return {"summary": "from fallback"}


def test_fallback_chain_uses_fallback_on_outage():
    llm = FallbackLLM(_DeadLLM(), [_AliveLLM()])
    assert llm.complete("s", "p") == "fallback-text"
    assert llm.complete_json("s", "p") == {"summary": "from fallback"}


def test_fallback_returns_empty_dict_when_all_fail():
    llm = FallbackLLM(_DeadLLM(), [_DeadLLM()])
    assert llm.complete_json("s", "p") == {}  # nodes use deterministic defaults
    with pytest.raises(RuntimeError):
        llm.complete("s", "p")


def test_get_llm_provider_wraps_fallback(monkeypatch):
    providers._llm_providers_cache.clear()
    providers._llm_fallback_wrapped.clear()
    monkeypatch.setattr(providers.runtime_settings, "get_value", lambda k: "ollama")
    monkeypatch.setattr(
        providers, "get_settings",
        lambda: type("S", (), {
            "ollama_base_url": "http://localhost:11434",
            "ollama_model": "m",
            "llm_fallback_provider": "mock",
        })(),
    )
    llm = providers.get_llm_provider()
    assert isinstance(llm, FallbackLLM)

    providers._llm_fallback_wrapped.clear()
    monkeypatch.setattr(
        providers, "get_settings",
        lambda: type("S", (), {
            "ollama_base_url": "http://localhost:11434",
            "ollama_model": "m",
            "llm_fallback_provider": "",
        })(),
    )
    llm = providers.get_llm_provider()
    assert not isinstance(llm, FallbackLLM)


# ── node logging ───────────────────────────────────────────────────────


def test_graph_nodes_emit_structured_logs(caplog):
    import logging as pylogging

    from src.agents.graph import create_workflow

    with caplog.at_level(pylogging.INFO, logger="src.agents.graph"):
        create_workflow().invoke(
            {
                "task_id": "log-test",
                "topic": "t",
                "platforms": ["twitter"],
                "brand_context": {"content_type": "text"},
                "revision_count": 0,
            }
        )
    assert "[node:researcher] start" in caplog.text
    assert "[node:critic] done" in caplog.text


# ── autopilot ──────────────────────────────────────────────────────────


def _autopilot_brand(session, **kw):
    brand = Brand(
        name=kw.get("name", "AutoBrand"),
        niche="tech",
        keywords=["robotics"],
        platforms=["twitter"],
        autopilot=True,
    )
    session.add(brand)
    session.commit()
    session.refresh(brand)
    return brand


def test_autopilot_creates_task_then_auto_approves(client, session, monkeypatch):
    from src.core import runtime_settings
    from src.services.autopilot_service import autopilot_tick

    monkeypatch.setattr(
        researcher,
        "search_hot_topics",
        lambda queries, **k: [
            {"title": "Robots learn to dance", "link": "", "published": "",
             "source": "X", "query": "robotics"},
        ],
    )
    runtime_settings.set_value("autopilot_enabled", True)
    brand = _autopilot_brand(session)

    first = autopilot_tick(session)
    assert first["tasks_created"] == 1  # task created, drafts land in REVIEW

    second = autopilot_tick(session)
    assert second["tasks_created"] == 0  # cooldown respected
    assert second["auto_approved"] == 1  # the twitter draft auto-approved

    contents = client.get("/api/contents").json()
    assert contents[0]["status"] == "approved"  # scheduled (+1h), awaiting due


def test_autopilot_kill_switch(session):
    from src.core import runtime_settings
    from src.services.autopilot_service import autopilot_tick

    runtime_settings.set_value("autopilot_enabled", False)
    _autopilot_brand(session)
    result = autopilot_tick(session)
    assert result == {
        "auto_approved": 0, "tasks_created": 0, "dispatched_due": 0,
        "brands": [], "disabled": True,
    }


# ── local diffusion providers (dependency guard) ───────────────────────


def test_local_media_requires_optional_deps(monkeypatch):
    """Without torch/diffusers the local providers fail with instructions."""
    import builtins

    from src.agents.local_media import LocalDiffusionImage, _load_torch

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in ("torch", "diffusers"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="requirements-local.txt"):
        _load_torch()
    monkeypatch.undo()
    # Constructor itself is cheap and must not pull heavy deps.
    assert LocalDiffusionImage()._model_id


def test_local_video_segment_math():
    from src.agents.local_media import LocalDiffusionVideo

    provider = LocalDiffusionVideo()
    assert provider._segment_count(2) == 1
    assert provider._segment_count(5) == 1
    assert provider._segment_count(6) == 2
    assert provider._segment_count(40) == 8
    assert provider._segment_count(60) == 12


def test_autopilot_rotates_platforms(session, monkeypatch):
    from src.core import runtime_settings
    from src.core.models import ContentTask
    from src.services.autopilot_service import _next_platform, autopilot_tick

    monkeypatch.setattr(
        researcher,
        "search_hot_topics",
        lambda queries, **k: [
            {"title": "Fresh robotics story", "link": "", "published": "",
             "source": "X", "query": "robotics"},
        ],
    )
    runtime_settings.set_value("autopilot_enabled", True)
    runtime_settings.set_value("autopilot_interval_hours", 1)
    brand = Brand(name="Rotator", niche="tech", keywords=["robotics"],
                  platforms=["twitter", "instagram", "tiktok"], autopilot=True)
    session.add(brand)
    session.commit()

    assert _next_platform(session, brand) == ["twitter"]
    autopilot_tick(session)
    assert _next_platform(session, brand) == ["instagram"]
    autopilot_tick(session)  # cooldown: no new task, rotation unchanged
    assert _next_platform(session, brand) == ["instagram"]

    # Force the interval to pass, then rotation advances.
    task = session.exec(
        __import__("sqlmodel").select(ContentTask)
        .where(ContentTask.brand_id == brand.id)
    ).first()
    task.created_at = task.created_at - __import__("datetime").timedelta(hours=2)
    session.add(task)
    session.commit()
    autopilot_tick(session)
    assert _next_platform(session, brand) == ["tiktok"]


def test_device_selection_prefers_cuda_then_mps(monkeypatch):
    from src.agents import local_media

    class _MPS:
        @staticmethod
        def is_available():
            return True

    class FakeTorch:
        float16 = "f16"
        float32 = "f32"
        bfloat16 = "bf16"

        class backends:
            mps = _MPS

        @staticmethod
        def cuda_is_available():
            return False

    FakeTorch.cuda = type("cuda", (), {"is_available": staticmethod(lambda: False)})
    device, dtype = local_media._device_and_dtype(FakeTorch)
    assert device == "mps" and dtype == "f16"

    FakeTorch.cuda = type("cuda", (), {"is_available": staticmethod(lambda: True)})
    device, dtype = local_media._device_and_dtype(FakeTorch)
    assert device == "cuda"

    FakeTorch.cuda = type("cuda", (), {"is_available": staticmethod(lambda: False)})
    monkeypatch.setattr(FakeTorch.backends, "mps", None)
    device, dtype = local_media._device_and_dtype(FakeTorch)
    assert device == "cpu" and dtype == "f32"
