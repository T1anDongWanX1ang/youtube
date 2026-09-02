"""Helpers for making viewpoint source URLs unique per extracted opinion."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def build_youtube_viewpoint_url(video_id: str, ordinal: int) -> str:
    """Return the canonical YouTube URL for one numbered viewpoint.

    ``o`` is deliberately part of the URL instead of a separate database field:
    predx_news deduplicates on ``source_url``.  A video may yield several
    viewpoints, so each one must have a distinct, still-valid URL.
    """
    if ordinal < 1:
        raise ValueError("viewpoint ordinal must be at least 1")
    return f"https://www.youtube.com/watch?v={video_id}&o={ordinal}"


def with_viewpoint_ordinal(source_url: str, ordinal: int) -> str:
    """Replace any existing ``o`` query parameter with ``ordinal``.

    This keeps the history migration idempotent and preserves any URL fields
    other than the deduplication suffix.
    """
    if ordinal < 1:
        raise ValueError("viewpoint ordinal must be at least 1")
    parsed = urlsplit(source_url)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
             if key != "o"]
    query.append(("o", str(ordinal)))
    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urlencode(query),
        parsed.fragment,
    ))
