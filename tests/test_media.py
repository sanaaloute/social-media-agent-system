"""Media serving route + real playable mock video (§9 panel previews)."""
import os

from tests.doubles import StubVideo
from src.core.config import get_settings


def test_media_route_serves_cached_file(client):
    media_dir = get_settings().media_cache_dir
    rel = os.path.join("task-x", "instagram", "image_1.png")
    full = os.path.join(media_dir, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n-fake")

    resp = client.get("/media/task-x/instagram/image_1.png")
    assert resp.status_code == 200
    assert resp.content.startswith(b"\x89PNG")


def test_media_route_rejects_traversal(client):
    resp = client.get("/media/..%2F..%2F.env")
    assert resp.status_code in (400, 403, 404)  # never serves outside the cache


def test_media_route_404_for_missing(client):
    assert client.get("/media/nope/missing.png").status_code == 404


def test_mock_video_writes_real_playable_mp4(tmp_path):
    paths = StubVideo().generate("test clip", str(tmp_path), count=1)
    with open(paths[0], "rb") as fh:
        header = fh.read(12)
    # ISO base media file format: bytes 4-8 are the 'ftyp' box marker.
    assert header[4:8] == b"ftyp", header
