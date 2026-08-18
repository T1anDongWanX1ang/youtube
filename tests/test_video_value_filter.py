from datetime import datetime, timezone

from youtube_crypto.models import YouTubeVideo
from youtube_crypto.services.video_value_filter import (
    VideoValueDecision,
    score_video_for_analysis,
    select_videos_for_analysis,
)


def _video(
    title: str,
    *,
    description: str = "",
    duration: int = 900,
    channel_priority: int | None = None,
) -> YouTubeVideo:
    return YouTubeVideo(
        video_id=title.lower().replace(" ", "-")[:40],
        channel_id="c",
        title=title,
        description=description,
        published_at=datetime(2026, 6, 23, tzinfo=timezone.utc),
        duration_seconds=duration,
        view_count=1000,
        channel_priority=channel_priority,
    )


def test_uses_channel_title_from_video_metadata():
    video = _video("Weekly global markets outlook")
    video.channel_title = "Real Vision"

    decision = score_video_for_analysis(video)

    assert decision.decision == "analyze"
    assert "macro_channel" in decision.reason


def test_scores_macro_politics_and_geopolitics_above_crypto():
    macro = score_video_for_analysis(
        _video("Fed rate decision, inflation and recession risks"),
        channel_title="Real Vision",
    )
    geopolitical = score_video_for_analysis(
        _video("Iran Israel ceasefire talks and oil market sanctions"),
        channel_title="CSIS",
    )
    crypto = score_video_for_analysis(
        _video("Bitcoin Ethereum Solana crypto bull market update"),
        channel_title="Coin Bureau",
    )

    assert macro.decision == "analyze"
    assert geopolitical.decision == "analyze"
    assert crypto.decision == "analyze"
    assert macro.score > crypto.score
    assert geopolitical.score > crypto.score


def test_skips_short_noise_and_sports_betting():
    short = score_video_for_analysis(_video("Fed inflation update", duration=90))
    betting = score_video_for_analysis(
        _video("MLB betting picks and best sportsbook odds"),
        channel_title="WagerTalk TV",
    )

    assert short.decision == "skip"
    assert "short" in short.reason
    assert betting.decision == "skip"
    assert "sports_betting" in betting.reason


def test_selects_highest_value_videos_before_transcription():
    videos = [
        _video("Bitcoin price chart update"),
        _video("Fed rates inflation jobs report and dollar market outlook"),
        _video("Celebrity podcast funny moments"),
        _video("Ukraine Russia ceasefire NATO sanctions and oil markets"),
    ]

    selected = select_videos_for_analysis(videos, limit=2)

    assert all(isinstance(item, VideoValueDecision) for item in selected)
    assert [item.video.title for item in selected] == [
        "Fed rates inflation jobs report and dollar market outlook",
        "Ukraine Russia ceasefire NATO sanctions and oil markets",
    ]


def test_selects_with_category_quotas_for_daily_top50_shape():
    videos = (
        [_video(f"Iran Israel ceasefire sanctions oil markets update {i}") for i in range(8)]
        + [_video(f"Fed rates inflation jobs dollar market outlook {i}") for i in range(4)]
        + [_video(f"OpenAI Nvidia Tesla earnings AI market update {i}") for i in range(3)]
        + [_video(f"Bitcoin Ethereum Solana crypto market update {i}") for i in range(2)]
    )

    selected = select_videos_for_analysis(videos, limit=10)
    counts: dict[str, int] = {}
    for decision in selected:
        counts[decision.category_hint] = counts.get(decision.category_hint, 0) + 1

    assert len(selected) == 10
    assert counts == {
        "politics_geopolitics": 5,
        "macro_market": 3,
        "business_tech": 2,
    }


def test_high_priority_kol_hot_event_commentary_is_boosted():
    low_priority = score_video_for_analysis(
        _video("Iran Israel ceasefire sanctions and oil markets update", channel_priority=0)
    )
    kol = score_video_for_analysis(
        _video("Iran Israel ceasefire sanctions and oil markets update", channel_priority=15)
    )

    assert kol.score > low_priority.score
    assert "high_priority_kol_hot_event" in kol.reason
