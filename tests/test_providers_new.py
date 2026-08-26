"""New providers: OpenRouter (hosted gateway), kie.ai (unified media),
and the configurable Ollama model — key handling and the kie.ai async
createTask -> recordInfo -> download flow (with fake httpx, no network).
"""
import json

import pytest

from src.agents import providers
from src.agents.providers import KieImage, KieVideo, OllamaLLM, OpenRouterLLM


def test_openrouter_requires_key(monkeypatch):
    monkeypatch.setattr(
        providers, "get_settings",
        lambda: type("S", (), {"openrouter_api_key": "", "openrouter_model": "m"})(),
    )
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        OpenRouterLLM()


def test_kie_requires_key(monkeypatch):
    monkeypatch.setattr(
        providers, "get_settings",
        lambda: type("S", (), {"kie_api_key": ""})(),
    )
    with pytest.raises(RuntimeError, match="KIE_API_KEY"):
        KieImage()


def test_ollama_model_is_configurable(monkeypatch):
    monkeypatch.setattr(
        providers, "get_settings",
        lambda: type("S", (), {"ollama_base_url": "http://x:11434",
                               "ollama_model": "qwen2.5:7b"})(),
    )
    assert OllamaLLM()._model == "qwen2.5:7b"


def _settings_stub(**kw):
    defaults = {"kie_api_key": "k", "kie_image_model": "img-model",
                "kie_video_model": "vid-model"}
    defaults.update(kw)
    return lambda: type("S", (), defaults)()


def test_kie_image_flow(monkeypatch, tmp_path):
    """createTask -> recordInfo(success) -> download, URLs found in nested JSON."""
    monkeypatch.setattr(providers, "get_settings", _settings_stub())
    monkeypatch.setattr(providers.time, "sleep", lambda s: None)

    calls = []

    class FakeResp:
        def __init__(self, payload=None, content=b""):
            self._payload = payload
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(("POST", url))
        assert url.endswith("/api/v1/jobs/createTask")
        assert json["model"] == "img-model"
        return FakeResp({"code": 200, "data": {"taskId": "task-1"}})

    def fake_get(url, params=None, headers=None, timeout=None, follow_redirects=False):
        calls.append(("GET", url))
        if "recordInfo" in url:
            assert params == {"taskId": "task-1"}
            # resultJson arrives as a *string* containing the URLs (per kie.ai)
            return FakeResp({
                "code": 200,
                "data": {
                    "taskId": "task-1",
                    "state": "success",
                    "resultJson": json.dumps({"resultUrls": ["https://cdn.kie.ai/x/out.png"]}),
                },
            })
        return FakeResp(content=b"png-bytes")

    monkeypatch.setattr(providers.httpx, "post", fake_post)
    monkeypatch.setattr(providers.httpx, "get", fake_get)

    paths = KieImage().generate("a cat", str(tmp_path), count=1)
    assert len(paths) == 1
    with open(paths[0], "rb") as fh:
        assert fh.read() == b"png-bytes"


def test_kie_task_failure_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "get_settings", _settings_stub())
    monkeypatch.setattr(providers.time, "sleep", lambda s: None)

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    monkeypatch.setattr(
        providers.httpx, "post",
        lambda *a, **k: FakeResp({"code": 200, "data": {"taskId": "t"}}),
    )
    monkeypatch.setattr(
        providers.httpx, "get",
        lambda *a, **k: FakeResp({"code": 200, "data": {"state": "fail", "failMsg": "bad prompt"}}),
    )

    with pytest.raises(RuntimeError, match="failed"):
        KieVideo().generate("anything", str(tmp_path))


def test_find_media_urls_nested():
    payload = {
        "state": "success",
        "resultJson": "{\"resultUrls\": [\"https://cdn/x/a.mp4?sig=1\"]}",
        "other": {"nested": ["ignore", "https://cdn/x/b.txt"]},
    }
    assert providers._find_media_urls(payload) == ["https://cdn/x/a.mp4?sig=1"]


def test_merge_llm_schema_per_field_fallback():
    """The exact qwen failure mode: wrong-typed fields revert, good ones stay."""
    from src.agents.providers import merge_llm_schema
    from src.core.models.schemas import ContentPlan

    defaults = {
        "angle": "default angle",
        "guidelines": "default guidelines",
        "schedule": {"twitter": "2026-01-01T00:00:00+00:00"},
    }
    llm_bad = {
        "angle": "LLM angle",  # good type — kept
        "guidelines": {"Twitter": ["nested"]},  # dict where str belongs — reverted
        "schedule": {"twitter": [{"Twitter": "2023"}]},  # list where str belongs — reverted
    }
    plan = merge_llm_schema(ContentPlan, defaults, llm_bad)
    assert plan.angle == "LLM angle"
    assert plan.guidelines == "default guidelines"
    assert plan.schedule == {"twitter": "2026-01-01T00:00:00+00:00"}


def test_planner_survives_bad_llm_types(monkeypatch):
    from src.agents import planner

    class BadLLM:
        def complete_json(self, system, prompt):
            return {
                "guidelines": {"Twitter": ["Share short posts"]},
                "schedule": {"twitter": [{"Twitter": "2023-10-01T15:00:00Z"}]},
            }

    monkeypatch.setattr(planner, "get_llm_provider", lambda: BadLLM())
    out = planner_agent_output = planner.planner_agent(
        {"topic": "AI adoption", "platforms": ["twitter"], "research_results": {}}
    )
    plan = out["content_plan"]
    assert isinstance(plan["guidelines"], str)
    assert isinstance(plan["schedule"]["twitter"], str)
    assert out["status"] == "planned"
