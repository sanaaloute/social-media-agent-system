"""End-to-end agent pipeline with mock providers (§3.2).

The full graph runs keyless: research → plan → write → image/video → critic
→ publisher (packages for HITL, does NOT publish).
"""
import os
from datetime import datetime

import httpx
from sqlmodel import select

from src.agents import run_generation
from src.agents.providers import MockImage, MockVideo
from src.core.models import ApprovalStatus, ContentTask, GeneratedContent, TaskStatus


def _task_contents(session, task_id):
    return session.exec(
        select(GeneratedContent).where(GeneratedContent.task_id == task_id)
    ).all()


def test_full_pipeline_produces_reviewable_drafts(session):
    task = ContentTask(
        brand_id="brand-1",
        platforms=["twitter", "linkedin"],
        topic="AI in healthcare",
        content_type="text",
    )
    session.add(task)
    session.commit()

    result = run_generation(task.id)

    assert result["status"] == "generated"
    assert len(result["content_ids"]) == 2

    contents = _task_contents(session, task.id)
    assert {c.platform for c in contents} == {"twitter", "linkedin"}
    for c in contents:
        assert c.status == ApprovalStatus.REVIEW.value
        assert c.text  # every draft has copy
        assert c.media_urls == []  # text task: no media assets
        assert "quality_report" in c.meta
        assert "content_plan" in c.meta

    session.refresh(task)
    assert task.status == TaskStatus.GENERATED.value


def test_pipeline_unknown_task_raises():
    import pytest

    with pytest.raises(ValueError):
        run_generation("no-such-task")


def test_mock_image_provider_writes_png(tmp_path):
    paths = MockImage().generate("a cat sitting on a keyboard", str(tmp_path), count=2)
    assert len(paths) == 2
    for p in paths:
        assert os.path.exists(p)
        with open(p, "rb") as fh:
            assert fh.read(8) == b"\x89PNG\r\n\x1a\n"


def test_mock_video_provider_writes_file(tmp_path):
    paths = MockVideo().generate("10s product teaser", str(tmp_path), count=1)
    assert len(paths) == 1
    assert os.path.exists(paths[0])
    assert os.path.getsize(paths[0]) > 0


def test_media_is_isolated_per_platform(session):
    task = ContentTask(
        brand_id="brand-1",
        platforms=["instagram", "tiktok"],
        topic="New product launch",
        content_type="mixed",
    )
    session.add(task)
    session.commit()

    result = run_generation(task.id)
    assert result["status"] == "generated"

    by_platform = {c.platform: c for c in _task_contents(session, task.id)}
    ig = [p.replace("\\", "/") for p in by_platform["instagram"].media_urls]
    tiktok = [p.replace("\\", "/") for p in by_platform["tiktok"].media_urls]
    assert ig and all("/instagram/" in p and p.endswith(".png") for p in ig)
    assert tiktok and all("/tiktok/" in p and p.endswith(".mp4") for p in tiktok)
    assert not (set(ig) & set(tiktok))


def test_task_content_type_wins_over_platform_default(session):
    image_task = ContentTask(
        brand_id="brand-1",
        platforms=["twitter"],
        topic="Product photo drop",
        content_type="image",
    )
    session.add(image_task)
    session.commit()

    result = run_generation(image_task.id)
    assert result["status"] == "generated"

    (twitter,) = _task_contents(session, image_task.id)
    paths = [p.replace("\\", "/") for p in twitter.media_urls]
    assert any("/twitter/" in p and p.endswith(".png") for p in paths)

    text_task = ContentTask(
        brand_id="brand-1",
        platforms=["instagram"],
        topic="Text-only announcement",
        content_type="text",
    )
    session.add(text_task)
    session.commit()

    result = run_generation(text_task.id)
    assert result["status"] == "generated"

    (instagram,) = _task_contents(session, text_task.id)
    assert instagram.media_urls == []


def test_image_provider_network_error_does_not_kill_run(session, monkeypatch):
    def _boom(self, prompt, out_dir, count=1):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(MockImage, "generate", _boom)

    task = ContentTask(
        brand_id="brand-1",
        platforms=["instagram"],
        topic="Fail whale",
        content_type="image",
    )
    session.add(task)
    session.commit()

    result = run_generation(task.id)

    assert result["status"] == "generated"
    contents = _task_contents(session, task.id)
    assert len(contents) == 1
    assert contents[0].text  # the draft itself still persists
    assert contents[0].media_urls == []

    session.refresh(task)
    assert task.status == TaskStatus.GENERATED.value


def test_task_scheduled_at_propagates_to_content(session):
    when = datetime(2030, 1, 2, 3, 4, 5)
    task = ContentTask(
        brand_id="brand-1",
        platforms=["twitter", "linkedin"],
        topic="Scheduled post",
        content_type="text",
        scheduled_at=when,
    )
    session.add(task)
    session.commit()

    result = run_generation(task.id)
    assert result["status"] == "generated"

    contents = _task_contents(session, task.id)
    assert len(contents) == 2
    assert all(c.scheduled_at == when for c in contents)
