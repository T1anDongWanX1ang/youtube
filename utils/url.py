"""Parse a YouTube URL (or bare id) into an 11-character video_id."""

import re
from urllib.parse import parse_qs, urlparse

_ID = re.compile(r"^[a-zA-Z0-9_-]{11}$")


def extract_video_id(url: str) -> str:
    """Extract the 11-char YouTube video_id from a URL or a bare id.

    Supports standard watch URLs, youtu.be short links (with or without extra
    query params such as ``&t=42s``) and bare ids. Raises ``ValueError`` when no
    YouTube video_id can be found.
    """
    s = (url or "").strip()
    if _ID.match(s):
        return s

    p = urlparse(s)
    if p.hostname in ("youtu.be",):
        vid = p.path.lstrip("/").split("/")[0]
        if _ID.match(vid):
            return vid
    if p.hostname and "youtube.com" in p.hostname:
        vid = parse_qs(p.query).get("v", [None])[0]
        if vid and _ID.match(vid):
            return vid
        parts = [seg for seg in p.path.split("/") if seg]
        if parts and _ID.match(parts[-1]):
            return parts[-1]

    raise ValueError(f"cannot extract youtube video_id from: {url!r}")
