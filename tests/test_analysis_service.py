import json
from datetime import datetime, timezone

import youtube_crypto.services.analysis_service as a_mod
from youtube_crypto.models import YouTubeVideo
from youtube_crypto.services.analysis_service import VideoAnalysisService


class _Settings:
    youtube_gemini_api_key = "k"
    gemini_model = "gemini-3-pro-preview"
    transcription_model = "gemini-2.5-flash"


def _video():
    return YouTubeVideo(
        video_id="v",
        channel_id="c",
        title="BTC update",
        description="desc",
        published_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        duration_seconds=600,
    )


def test_analyze_parses_claims_and_legacy_fields(monkeypatch):
    payload = json.dumps(
        {
            "speaker": "Coin Bureau",
            "category": "market",
            "is_substantive": True,
            "overall_thesis": "BTC trends up into Q3",
            "sentiment": "bullish",
            "conviction_score": 70,
            "risk_score": 40,
            "assets": ["BTC"],
            "key_tokens": ["BTC"],
            "narratives": ["ETF"],
            "key_narratives": ["ETF"],
            "events_referenced": ["spot BTC ETF flows"],
            "summary_brief": "brief",
            "summary_detailed": "detailed",
            "summary_full": "full",
            "claims": [
                {
                    "claim_text": "BTC reclaims 120k by Q3 end",
                    "type": "price_target",
                    "asset": "BTC",
                    "direction": "bullish",
                    "target": "$120k",
                    "timeframe": "Q3 2026",
                    "verbatim_quote": "BTC is going to 120k",
                    "timestamp": "12:30",
                    "how_to_verify": "BTC price >= 120k at Q3 end",
                }
            ],
            "catalysts_mentioned": [
                {"event": "ETF decision", "dateOrWindow": "Q3", "direction": "bullish", "description": "d"}
            ],
            "risks_mentioned": ["regulatory crackdown"],
        }
    )
    monkeypatch.setattr(a_mod, "generate_text", lambda **kw: (payload, {"totalTokenCount": 10}))

    result = VideoAnalysisService(settings=_Settings()).analyze_video(
        _video(), "[00:00] hello [12:30] BTC is going to 120k", "v2"
    )

    assert result is not None
    assert result.speaker == "Coin Bureau"
    assert result.category == "market"
    assert result.key_tokens == ["BTC"]
    assert result.key_narratives == ["ETF"]
    assert result.events_referenced == ["spot BTC ETF flows"]
    assert result.summary_brief == "brief"
    assert len(result.claims) == 1
    assert result.claims[0]["target"] == "$120k"
    assert result.claims[0]["timestamp"] == "12:30"
    assert result.transcript is None  # transcript lives in its own table


def test_analyze_skips_non_substantive(monkeypatch):
    payload = json.dumps({"is_substantive": False, "claims": []})
    monkeypatch.setattr(a_mod, "generate_text", lambda **kw: (payload, None))

    result = VideoAnalysisService(settings=_Settings()).analyze_video(_video(), "[00:00] sponsor read", "v2")
    assert result is None


def test_analyze_returns_none_without_transcript(monkeypatch):
    called = {"n": 0}

    def fake(**kw):
        called["n"] += 1
        return ("{}", None)

    monkeypatch.setattr(a_mod, "generate_text", fake)
    result = VideoAnalysisService(settings=_Settings()).analyze_video(_video(), "", "v2")
    assert result is None
    assert called["n"] == 0  # short-circuits before calling the model


def test_analyze_chunks_long_transcripts_and_requests_json_schema(monkeypatch):
    monkeypatch.setattr(a_mod, "ANALYSIS_TRANSCRIPT_CHUNK_CHARS", 80, raising=False)
    monkeypatch.setattr(a_mod, "CLAIM_ANALYSIS_MAX_CLAIMS_PER_CHUNK", 2, raising=False)
    calls = []

    def fake_generate_text(**kw):
        calls.append(kw)
        idx = len(calls)
        payload = json.dumps({
            "speaker": "Analyst",
            "category": "market",
            "is_substantive": True,
            "overall_thesis": f"chunk {idx}",
            "sentiment": "neutral",
            "assets": [],
            "key_tokens": [],
            "narratives": [],
            "key_narratives": [],
            "events_referenced": [],
            "summary_brief": f"brief {idx}",
            "claims": [{"claim_text": f"claim {idx}", "verbatim_quote": "quote", "timestamp": "00:01"}],
            "catalysts_mentioned": [],
            "risks_mentioned": [],
        })
        return payload, {"totalTokenCount": 10}

    monkeypatch.setattr(a_mod, "generate_text", fake_generate_text)
    transcript = "[00:00] " + ("macro rates risk. " * 30)

    result = VideoAnalysisService(settings=_Settings()).analyze_video(_video(), transcript, "v2")

    assert result is not None
    assert len(calls) > 1
    assert all(c["response_mime_type"] == "application/json" for c in calls)
    assert all(c["response_schema"]["type"] == "object" for c in calls)
    assert all(len(c["prompt"]) < len(transcript) + 2000 for c in calls)
    assert len(result.claims) == len(calls)


def test_join_limited_keeps_a_complete_english_sentence():
    text = "First complete sentence. Second sentence is deliberately much longer than the limit."

    result = a_mod._join_limited([text], 30)

    assert result == "First complete sentence."


def test_join_limited_keeps_a_complete_chinese_sentence():
    text = "这是第一句完整内容。第二句内容超过设置的截断上限，因此不应写入半句话。"

    result = a_mod._join_limited([text], 12)

    assert result == "这是第一句完整内容。"
