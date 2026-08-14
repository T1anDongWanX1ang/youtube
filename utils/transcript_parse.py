"""Parse a timestamped transcript (from the Gemini transcription prompt) into segments.

Each segment line starts with a ``[mm:ss]`` or ``[hh:mm:ss]`` marker. Lines without a
marker are treated as a continuation of the previous segment (so nothing is dropped from
the body), and any lines before the first timestamp (e.g. a ``LANG: en`` header) are
ignored.
"""
import re
from typing import List, Optional

_TS = re.compile(r"^\s*\[(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\]\s*(.*)$")


def parse_segments(raw: Optional[str]) -> List[dict]:
    """Parse raw transcript text into ``[{"start": <seconds:int>, "text": str}, ...]``."""
    segments: List[dict] = []
    for line in (raw or "").splitlines():
        match = _TS.match(line)
        if match:
            hours = int(match.group(1) or 0)
            minutes = int(match.group(2))
            seconds = int(match.group(3))
            start = hours * 3600 + minutes * 60 + seconds
            segments.append({"start": start, "text": match.group(4).strip()})
        else:
            stripped = line.strip()
            if stripped and segments:
                # Continuation of the previous segment - keep the content.
                segments[-1]["text"] = f"{segments[-1]['text']} {stripped}".strip()
    return segments
