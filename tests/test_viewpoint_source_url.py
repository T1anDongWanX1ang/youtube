from datetime import datetime

import pytest

from youtube_crypto.models import YouTubeVideo
from youtube_crypto.repositories.research_viewpoint_repository import ResearchViewpointRepository
from youtube_crypto.services.viewpoint_extraction_service import ViewpointDraft
from youtube_crypto.utils.viewpoint_url import build_youtube_viewpoint_url, with_viewpoint_ordinal


def _draft(title: str) -> ViewpointDraft:
    return ViewpointDraft(
        title=title,
        core_judgment="Judgment",
        subject="BTC",
        follow_up="Follow up",
    )


def test_youtube_viewpoint_url_has_a_valid_unique_ordinal():
    assert build_youtube_viewpoint_url("video-1", 2) == (
        "https://www.youtube.com/watch?v=video-1&o=2"
    )
    assert with_viewpoint_ordinal(
        "https://www.youtube.com/watch?v=video-1&o=99", 2
    ) == "https://www.youtube.com/watch?v=video-1&o=2"
    with pytest.raises(ValueError):
        build_youtube_viewpoint_url("video-1", 0)


def test_build_viewpoints_numbers_each_draft_from_one():
    video = YouTubeVideo(
        video_id="video-1",
        channel_id="channel-1",
        channel_title="Channel",
        title="Video",
        published_at=datetime(2026, 9, 1),
    )

    viewpoints = ResearchViewpointRepository.build_viewpoints(
        video=video,
        channel_handle="@channel",
        channel_title="Channel",
        drafts=[_draft("First"), _draft("Second")],
    )

    assert [item.source_url for item in viewpoints] == [
        "https://www.youtube.com/watch?v=video-1&o=1",
        "https://www.youtube.com/watch?v=video-1&o=2",
    ]
