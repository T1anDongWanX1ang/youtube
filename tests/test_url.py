import pytest
from youtube_crypto.utils.url import extract_video_id

_EXPECTED = "dQw4w9WgXcQ"


def test_standard_watch_url():
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == _EXPECTED


def test_short_youtu_be_url():
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == _EXPECTED


def test_watch_url_with_extra_query_params():
    assert (
        extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s") == _EXPECTED
    )


def test_short_url_with_timestamp():
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ?t=42s") == _EXPECTED


def test_bare_video_id():
    assert extract_video_id("dQw4w9WgXcQ") == _EXPECTED


def test_non_youtube_url_raises():
    with pytest.raises(ValueError):
        extract_video_id("https://example.com/watch?v=dQw4w9WgXcQ")


def test_garbage_input_raises():
    with pytest.raises(ValueError):
        extract_video_id("not a url")
