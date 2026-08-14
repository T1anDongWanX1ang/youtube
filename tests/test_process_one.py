import asyncio
from datetime import datetime, timezone

import pytest
from youtube_crypto.models import YouTubeVideo
from youtube_crypto.models.analysis import VideoAnalysis
from youtube_crypto.models.transcript import VideoTranscript
from youtube_crypto.services import process_one as process_one_mod
from youtube_crypto.services.process_one import ANALYSIS_VERSION, process_one


def _video():
    return YouTubeVideo(
        video_id="dQw4w9WgXcQ",
        channel_id="UC123",
        channel_title="Coin Bureau",
        title="BTC update",
        description="desc",
        published_at=datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc),
        duration_seconds=600,
    )


def _ok_transcript():
    return VideoTranscript(video_id="dQw4w9WgXcQ", full_text="hello world", ok=True)


def _analysis_with_claims():
    return VideoAnalysis(
        video_id="dQw4w9WgXcQ",
        analysis_version=ANALYSIS_VERSION,
        model_name="gemini-2.5-flash-lite",
        summary_brief="brief",
        claims=[{"claim_text": "BTC reclaims 120k by Q3 end"}],
    )


def test_process_one_sync_fakes_returns_expected_dict():
    captured = {}

    def fake_fetch(ids):
        captured["fetch_ids"] = ids
        return [_video()]

    def fake_transcribe(video):
        return _ok_transcript()

    def fake_analyze(video, transcript_text, analysis_version):
        captured["analysis_version"] = analysis_version
        captured["transcript_text"] = transcript_text
        return _analysis_with_claims()

    def fake_upsert_tx(tx):
        captured["upserted_tx"] = tx

    def fake_insert_an(an):
        captured["inserted_an"] = an

    deps = {
        "fetch": fake_fetch,
        "transcribe": fake_transcribe,
        "analyze": fake_analyze,
        "upsert_tx": fake_upsert_tx,
        "insert_an": fake_insert_an,
    }

    result = asyncio.run(
        process_one("https://www.youtube.com/watch?v=dQw4w9WgXcQ", _deps=deps)
    )

    assert result["video_id"] == "dQw4w9WgXcQ"
    assert result["title"] == "BTC update"
    assert result["channel_title"] == "Coin Bureau"
    assert result["published_at"] == "2026-05-20T12:00:00+00:00"
    assert result["claims_json"]["claims"][0]["claim_text"] == "BTC reclaims 120k by Q3 end"

    # Real-version string was forwarded to the analyzer.
    assert captured["analysis_version"] == ANALYSIS_VERSION
    assert captured["fetch_ids"] == ["dQw4w9WgXcQ"]
    assert captured["transcript_text"] == "hello world"
    assert captured["inserted_an"] is not None


def test_process_one_non_substantive_returns_empty_claims():
    def fake_fetch(ids):
        return [_video()]

    def fake_transcribe(video):
        return _ok_transcript()

    def fake_analyze(video, transcript_text, analysis_version):
        return None  # not substantive

    inserted = {"called": False}

    def fake_insert_an(an):
        inserted["called"] = True

    deps = {
        "fetch": fake_fetch,
        "transcribe": fake_transcribe,
        "analyze": fake_analyze,
        "upsert_tx": lambda tx: None,
        "insert_an": fake_insert_an,
    }

    result = asyncio.run(process_one("dQw4w9WgXcQ", _deps=deps))

    assert result["claims_json"] == {"claims": []}
    assert result["video_id"] == "dQw4w9WgXcQ"
    # Nothing to insert when analysis is None.
    assert inserted["called"] is False


def test_process_one_raises_on_empty_transcript():
    def fake_fetch(ids):
        return [_video()]

    def fake_transcribe(video):
        return VideoTranscript(video_id="dQw4w9WgXcQ", full_text="", ok=False)

    deps = {
        "fetch": fake_fetch,
        "transcribe": fake_transcribe,
        "analyze": lambda *a, **k: None,
        "upsert_tx": lambda tx: None,
        "insert_an": lambda an: None,
    }

    with pytest.raises(RuntimeError):
        asyncio.run(process_one("dQw4w9WgXcQ", _deps=deps))


def test_process_one_async_fakes():
    captured = {}

    async def fake_fetch(ids):
        return [_video()]

    async def fake_transcribe(video):
        return _ok_transcript()

    async def fake_analyze(video, transcript_text, analysis_version):
        return _analysis_with_claims()

    async def fake_upsert_tx(tx):
        captured["upserted_tx"] = tx

    async def fake_insert_an(an):
        captured["inserted_an"] = an

    deps = {
        "fetch": fake_fetch,
        "transcribe": fake_transcribe,
        "analyze": fake_analyze,
        "upsert_tx": fake_upsert_tx,
        "insert_an": fake_insert_an,
    }

    result = asyncio.run(process_one("https://youtu.be/dQw4w9WgXcQ?t=42s", _deps=deps))

    assert result["video_id"] == "dQw4w9WgXcQ"
    assert result["claims_json"]["claims"][0]["claim_text"] == "BTC reclaims 120k by Q3 end"
    assert captured["upserted_tx"] is not None
    assert captured["inserted_an"] is not None


def test_db_pool_is_created_once_and_reused(monkeypatch):
    # Reset any cached pool from a previous run so the counter is meaningful.
    process_one_mod._reset_db_pool_cache()

    created = {"count": 0}

    class _FakePool:
        pass

    fake_pool = _FakePool()

    class _FakeSettings:
        async def create_db_pool(self):
            created["count"] += 1
            return fake_pool

    # Avoid touching real env/DB: hand process_one a fake settings object whose
    # create_db_pool is a counter.
    monkeypatch.setattr(
        process_one_mod.YouTubeCryptoSettings, "from_env", staticmethod(_FakeSettings)
    )

    pool_a = asyncio.run(process_one_mod._get_db_pool())
    pool_b = asyncio.run(process_one_mod._get_db_pool())

    assert pool_a is fake_pool
    assert pool_b is fake_pool
    assert created["count"] == 1  # created once, reused on the second call

    # Clean up so the fake pool does not leak into other tests.
    process_one_mod._reset_db_pool_cache()
