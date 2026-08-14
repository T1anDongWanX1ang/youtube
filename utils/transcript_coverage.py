"""Coverage check for a parsed transcript.

Gates a transcript before it is allowed into the analysis stage: if the model truncated
the transcript well short of the video duration, we mark it failed instead of analysing a
partial source. This is the mechanism that prevents "the model only covered 10%".
"""
from typing import List


def compute_coverage(
    segments: List[dict],
    duration_seconds: int,
    min_ratio: float = 0.9,
) -> dict:
    """Return coverage metrics for ``segments`` against the known video duration.

    ``duration_covered_sec`` is the last segment's start time. When the video duration is
    unknown (0/None) we accept any non-empty transcript; otherwise we require coverage of
    at least ``min_ratio`` of the duration.
    """
    duration_covered = max((int(s.get("start", 0)) for s in segments), default=0)
    word_count = sum(len((s.get("text") or "").split()) for s in segments)

    if not duration_seconds or duration_seconds <= 0:
        ok = word_count > 0
    else:
        ok = (duration_covered / duration_seconds) >= min_ratio

    return {
        "duration_covered_sec": duration_covered,
        "word_count": word_count,
        "ok": ok,
    }
