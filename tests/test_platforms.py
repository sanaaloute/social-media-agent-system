"""Platform wiring: canonical registry, intake validation, agent coverage.

Guards against drafts being generated for platforms no adapter knows, and
against typos/casing producing unpublishable content (§4, §6.2).
"""
from src.agents.writer import writer_agent
from src.publishers import SUPPORTED_PLATFORMS, validate_platforms


def test_platforms_endpoint_lists_all_supported(client):
    platforms = client.get("/api/platforms").json()
    names = [p["name"] for p in platforms]
    assert set(names) == set(SUPPORTED_PLATFORMS)
    assert all(p["has_account"] is False for p in platforms)

    client.post(
        "/api/accounts",
        json={"platform": "twitter", "username": "@x",
              "tokens": {"access_token": "t"}},
    )
    platforms = {p["name"]: p for p in client.get("/api/platforms").json()}
    assert platforms["twitter"]["has_account"] is True
    assert platforms["facebook"]["has_account"] is False


def test_task_platforms_are_normalized_and_validated(client):
    # Mixed case is normalized instead of failing account matching later.
    resp = client.post(
        "/api/tasks",
        json={"platforms": ["Twitter", "LINKEDIN"],
              "topic": "t", "content_type": "text"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["platforms"] == ["twitter", "linkedin"]

    # Unknown platforms are rejected at intake, not at publish time.
    resp = client.post(
        "/api/tasks",
        json={"brand_id": "b", "platforms": ["myspace"], "topic": "t"},
    )
    assert resp.status_code == 400
    assert "myspace" in resp.json()["detail"]


def test_compose_platforms_are_validated(client):
    resp = client.post(
        "/api/compose", data={"text": "x", "platforms": "twitter,myspace"}
    )
    assert resp.status_code == 400


def test_validate_platforms_unit():
    assert validate_platforms([" Twitter ", "FACEBOOK"]) == ["twitter", "facebook"]
    try:
        validate_platforms(["orkut"])
    except ValueError as exc:
        assert "orkut" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_writer_covers_every_supported_platform():
    """Every supported platform gets a typed, styled draft (§3.2)."""
    state = {
        "topic": "product update",
        "platforms": sorted(SUPPORTED_PLATFORMS),
        "brand_context": {"content_type": "mixed"},
        "content_plan": {},
        "research_results": {},
        "quality_report": None,
    }
    drafts = writer_agent(state)["drafts"]
    assert set(drafts) == set(SUPPORTED_PLATFORMS)
    for platform, draft in drafts.items():
        assert draft["text"], platform
        assert draft["content_type"] in ("text", "image", "video")
    # Media-needing platforms are mapped so the media agents pick them up.
    assert drafts["instagram"]["content_type"] == "image"
    assert drafts["tiktok"]["content_type"] == "video"
    assert drafts["youtube"]["content_type"] == "video"
    assert drafts["facebook"]["content_type"] == "text"
