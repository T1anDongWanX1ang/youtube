import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..config.config import (
    VIDEO_DOMAIN_CATEGORIES,
    YouTubeCryptoSettings,
    get_prompt_path,
    resolve_gemini_api_key,
)
from ..models import YouTubeVideo
from ..utils.validation import validate_required_fields
from ..utils.gemini_rest import generate_from_video

logger = logging.getLogger(__name__)


def _strip_json_markers(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```json"):
        stripped = stripped[7:]
    elif stripped.startswith("```"):
        stripped = stripped[3:]
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    return stripped.strip()


def _extract_first_json_object(text: str) -> str:
    stripped = _strip_json_markers(text)
    start = stripped.find("{")
    if start == -1:
        return stripped

    depth = 0
    in_string = False
    escape = False
    end_index: Optional[int] = None

    for i, ch in enumerate(stripped[start:], start=start):
        if escape:
            escape = False
            continue

        if in_string:
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end_index = i
                break

    if end_index is not None and end_index >= start:
        return stripped[start : end_index + 1]

    return stripped[start:]


@dataclass
class VideoDomainRouterService:
    """
    Service that classifies a YouTube video into one of the supported content domains.
    """

    settings: YouTubeCryptoSettings

    def __post_init__(self) -> None:
        self._prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        prompt_path = get_prompt_path("router")
        try:
            return prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("Router prompt file not found at %s", prompt_path)
            return (
                "You are a video domain router. Classify the video into one primary domain "
                "from: politics, world, market, sports, economy, business_tech, other. "
                "Output only one valid JSON object with fields: primary_category, "
                "secondary_categories, routing_confidence, reason, next_prompt_key."
            )

    def classify_video(self, video: YouTubeVideo) -> Dict[str, Any]:
        youtube_url = f"https://www.youtube.com/watch?v={video.video_id}"

        start_time = time.perf_counter()
        try:
            full_text, _usage = generate_from_video(
                api_key=resolve_gemini_api_key(self.settings),
                model=self.settings.gemini_model,
                video_url=youtube_url,
                prompt=self._prompt,
                max_output_tokens=4096,
            )
        except Exception:
            logger.exception("Error while calling Gemini for video routing video_id=%s", video.video_id)
            raise
        elapsed_seconds = time.perf_counter() - start_time

        logger.debug("Raw Gemini routing response for video_id=%s: %s", video.video_id, full_text[:1000])

        try:
            parsed_text = _extract_first_json_object(full_text)
            data: Dict[str, Any] = json.loads(parsed_text)
        except json.JSONDecodeError:
            logger.exception(
                "Failed to parse JSON from Gemini routing response for video_id=%s. Parsed text (truncated): %s",
                video.video_id,
                full_text[:2000],
            )
            raise

        validate_required_fields(
            data,
            ["primary_category", "secondary_categories", "routing_confidence", "reason", "next_prompt_key"],
        )

        primary = data["primary_category"]
        if data["next_prompt_key"] != primary:
            raise ValueError("Router output next_prompt_key must equal primary_category")

        if primary not in VIDEO_DOMAIN_CATEGORIES:
            raise ValueError("Router output primary_category is not a supported domain")

        data["secondary_categories"] = [
            c for c in data.get("secondary_categories", [])
            if c in VIDEO_DOMAIN_CATEGORIES and c != primary
        ]

        if not isinstance(data["routing_confidence"], (int, float)):
            raise ValueError("Router output routing_confidence must be numeric")

        data["routing_confidence"] = float(data["routing_confidence"])
        data["elapsed_seconds"] = elapsed_seconds
        data["raw_text"] = full_text

        return data
