"""Extract distinct opinion-level viewpoints from a completed video analysis."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config.config import YouTubeCryptoSettings, resolve_gemini_api_key
from ..utils.gemini_rest import generate_text

logger = logging.getLogger(__name__)

POINT_OF_VIEW_MAX_OUTPUT_TOKENS = 8192
POINT_OF_VIEW_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["title", "core_judgement", "subject", "follow_up"],
        "properties": {
            "title": {"type": "string"},
            "core_judgement": {"type": "string"},
            "subject": {"type": "string"},
            "follow_up": {"type": "string"},
        },
    },
}


@dataclass(frozen=True)
class ViewpointDraft:
    title: str
    core_judgment: str
    subject: str
    follow_up: str


def _load_prompt() -> str:
    return (Path(__file__).parent.parent / "point_of_view_llm.txt").read_text(
        encoding="utf-8"
    )


def _extract_json_array(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```json"):
        stripped = stripped[7:]
    elif stripped.startswith("```"):
        stripped = stripped[3:]
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    start = stripped.find("[")
    end = stripped.rfind("]")
    return stripped[start : end + 1] if start >= 0 and end >= start else stripped


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


@dataclass
class ViewpointExtractionService:
    settings: YouTubeCryptoSettings

    def extract(self, summary_detailed: str, video_id: str) -> list[ViewpointDraft]:
        if not summary_detailed or not summary_detailed.strip():
            return []

        prompt = _load_prompt().replace("{{TRANSCRIPT}}", summary_detailed.strip())
        text, usage = generate_text(
            api_key=resolve_gemini_api_key(self.settings),
            model=self.settings.gemini_model,
            prompt=prompt,
            max_output_tokens=POINT_OF_VIEW_MAX_OUTPUT_TOKENS,
            temperature=0.1,
            base_url=getattr(self.settings, "gemini_base_url", None),
            response_mime_type="application/json",
            response_schema=POINT_OF_VIEW_RESPONSE_SCHEMA,
        )
        try:
            payload = json.loads(_extract_json_array(text))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Viewpoint response was not valid JSON for video_id={video_id}"
            ) from exc
        if not isinstance(payload, list):
            raise RuntimeError(f"Viewpoint response was not a JSON array for video_id={video_id}")

        drafts: list[ViewpointDraft] = []
        seen: set[tuple[str, str]] = set()
        for item in payload:
            if not isinstance(item, dict):
                continue
            draft = ViewpointDraft(
                title=_text(item.get("title"), 256),
                core_judgment=_text(item.get("core_judgement"), 20_000),
                subject=_text(item.get("subject"), 512),
                follow_up=_text(item.get("follow_up"), 20_000)
                or "None explicitly identified.",
            )
            if not draft.title or not draft.core_judgment or not draft.subject:
                logger.warning("Skipping incomplete viewpoint video_id=%s", video_id)
                continue
            key = (draft.title.casefold(), draft.core_judgment.casefold())
            if key not in seen:
                seen.add(key)
                drafts.append(draft)
        logger.info(
            "Extracted %d distinct viewpoints for video_id=%s tokens=%s",
            len(drafts),
            video_id,
            usage.get("totalTokenCount") if usage else None,
        )
        return drafts
