import youtube_crypto.web.app as webmod
from fastapi.testclient import TestClient
from youtube_crypto.web.app import app

client = TestClient(app)


def _fake_result():
    return {
        "video_id": "dQw4w9WgXcQ",
        "title": "BTC update",
        "channel_title": "Coin Bureau",
        "published_at": "2026-05-20T12:00:00+00:00",
        "claims_json": {"claims": [{"claim_text": "BTC reclaims 120k by Q3 end"}]},
    }


def test_process_one_happy_path(monkeypatch):
    async def fake_async(url):
        assert url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        return _fake_result()

    monkeypatch.setattr(webmod, "process_one", fake_async)

    resp = client.post(
        "/process-one",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["video_id"] == "dQw4w9WgXcQ"
    assert body["claims_json"]["claims"][0]["claim_text"] == "BTC reclaims 120k by Q3 end"


def test_process_one_bad_url_returns_400(monkeypatch):
    async def fake_async(url):
        raise ValueError("cannot extract youtube video_id")

    monkeypatch.setattr(webmod, "process_one", fake_async)

    resp = client.post("/process-one", json={"url": "not a youtube url"})

    assert resp.status_code == 400
    assert "error" in resp.json()


def test_process_one_upstream_failure_returns_502(monkeypatch):
    async def fake_async(url):
        raise RuntimeError("gemini exploded")

    monkeypatch.setattr(webmod, "process_one", fake_async)

    resp = client.post(
        "/process-one",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    )

    assert resp.status_code == 502
    body = resp.json()
    assert "error" in body
    assert "extract failed" in body["error"]
