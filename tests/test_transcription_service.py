from datetime import datetime, timezone

import youtube_crypto.services.transcription_service as ts_mod
from youtube_crypto.models import YouTubeVideo
from youtube_crypto.services.transcription_service import TranscriptionService


class _Settings:
    youtube_gemini_api_key = "k"
    transcription_model = "gemini-2.5-flash"
    gemini_model = "gemini-2.5-flash"


def _video(duration=1800):
    return YouTubeVideo(
        video_id="vid1",
        channel_id="c",
        title="t",
        published_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        duration_seconds=duration,
    )


def test_transcribe_continues_until_covered(monkeypatch):
    calls = []
    responses = [
        ("LANG: en\n[00:00] intro\n[15:00] middle", {"totalTokenCount": 10}),  # covers 900/1800
        ("[15:30] more\n[29:10] end", {"totalTokenCount": 5}),                  # covers 1750/1800
    ]

    def fake(**kwargs):
        calls.append(kwargs)
        return responses[len(calls) - 1]

    monkeypatch.setattr(ts_mod, "generate_from_video", fake)

    transcript = TranscriptionService(settings=_Settings()).transcribe(_video(1800))

    assert len(calls) == 2
    assert transcript.ok is True
    assert transcript.language == "en"
    assert transcript.duration_covered_sec == 1750
    assert "Resume the transcript from" in calls[1]["prompt"]
    # merged, in order, no duplicate of the first-pass segments
    assert [s["start"] for s in transcript.segments] == [0, 900, 930, 1750]


def test_transcribe_marks_failed_when_cannot_cover(monkeypatch):
    def fake(**kwargs):
        return ("LANG: en\n[00:00] only the very beginning", {"totalTokenCount": 3})

    monkeypatch.setattr(ts_mod, "generate_from_video", fake)

    transcript = TranscriptionService(settings=_Settings()).transcribe(_video(1800))

    assert transcript.ok is False
    assert transcript.word_count > 0


def test_transcribe_skips_direct_gemini_for_overlong_video(monkeypatch):
    monkeypatch.setattr(ts_mod, "TRANSCRIBE_MAX_DIRECT_VIDEO_SECONDS", 3600, raising=False)

    def fake(**kwargs):
        raise AssertionError("overlong videos must not be sent to Gemini as one file")

    monkeypatch.setattr(ts_mod, "generate_from_video", fake)

    transcript = TranscriptionService(settings=_Settings()).transcribe(_video(duration=7200))

    assert transcript.ok is False
    assert transcript.word_count == 0
    assert transcript.duration_covered_sec == 0
