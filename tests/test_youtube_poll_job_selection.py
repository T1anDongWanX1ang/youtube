from datetime import datetime, timezone

from youtube_crypto.jobs.youtube_poll_job import (
    _remaining_transcription_capacity,
    _select_transcription_candidates,
)
from youtube_crypto.models import YouTubeVideo


def _video(title: str) -> YouTubeVideo:
    return YouTubeVideo(
        video_id=title.lower().replace(" ", "-")[:40],
        channel_id="c",
        title=title,
        description="",
        published_at=datetime(2026, 6, 23, tzinfo=timezone.utc),
        duration_seconds=900,
    )


def test_transcription_batch_uses_value_filter_before_calling_gemini():
    videos = [
        _video("Celebrity gossip funny moments"),
        _video("Fed rates inflation and recession market outlook"),
        _video("MLB betting picks and sportsbook odds"),
        _video("Iran Israel ceasefire sanctions and oil markets"),
    ]

    selected = _select_transcription_candidates(videos, limit=2)

    assert [item.video.title for item in selected] == [
        "Fed rates inflation and recession market outlook",
        "Iran Israel ceasefire sanctions and oil markets",
    ]


def test_daily_transcription_capacity_blocks_extra_loop_batches():
    assert _remaining_transcription_capacity(processed_today=0, daily_limit=50, batch_size=50) == 50
    assert _remaining_transcription_capacity(processed_today=35, daily_limit=50, batch_size=50) == 15
    assert _remaining_transcription_capacity(processed_today=50, daily_limit=50, batch_size=50) == 0
