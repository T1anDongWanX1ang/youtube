import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from ..config.config import YouTubeCryptoSettings, resolve_gemini_api_key
from ..models import VideoAnalysis, YouTubeVideo
from ..utils.gemini_rest import generate_text

logger = logging.getLogger(__name__)

# Flash-Lite occasionally needs more than 8K tokens to complete a structured
# response despite the prompt's compact-output contract. Keep this configurable,
# with 16K as the safe default so a complete JSON response is not discarded.
ANALYSIS_MAX_OUTPUT_TOKENS = int(os.getenv("YOUTUBE_ANALYSIS_MAX_OUTPUT_TOKENS", "16384"))
ANALYSIS_TRANSCRIPT_CHUNK_CHARS = int(os.getenv("YOUTUBE_ANALYSIS_TRANSCRIPT_CHUNK_CHARS", "4000"))
CLAIM_ANALYSIS_MAX_CLAIMS_PER_CHUNK = int(os.getenv("YOUTUBE_ANALYSIS_MAX_CLAIMS_PER_CHUNK", "1"))
CLAIM_TEXT_MAX_CHARS = int(os.getenv("YOUTUBE_ANALYSIS_CLAIM_TEXT_MAX_CHARS", "280"))
QUOTE_MAX_CHARS = int(os.getenv("YOUTUBE_ANALYSIS_QUOTE_MAX_CHARS", "220"))
SUMMARY_BRIEF_MAX_CHARS = int(os.getenv("YOUTUBE_ANALYSIS_SUMMARY_BRIEF_MAX_CHARS", "280"))
SUMMARY_DETAILED_MAX_CHARS = int(os.getenv("YOUTUBE_ANALYSIS_SUMMARY_DETAILED_MAX_CHARS", "3000"))
SUMMARY_FULL_MAX_CHARS = int(os.getenv("YOUTUBE_ANALYSIS_SUMMARY_FULL_MAX_CHARS", "6000"))
SUMMARY_DETAILED_PER_CHUNK_MAX_CHARS = int(
    os.getenv("YOUTUBE_ANALYSIS_SUMMARY_DETAILED_PER_CHUNK_MAX_CHARS", "1200")
)
SUMMARY_FULL_PER_CHUNK_MAX_CHARS = int(
    os.getenv("YOUTUBE_ANALYSIS_SUMMARY_FULL_PER_CHUNK_MAX_CHARS", "2000")
)
ANALYSIS_CHUNK_COOLDOWN_SECONDS = float(os.getenv("YOUTUBE_ANALYSIS_CHUNK_COOLDOWN_SECONDS", "3"))

CLAIM_ANALYSIS_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "speaker", "category", "is_substantive", "overall_thesis", "sentiment",
        "assets", "key_tokens", "narratives", "key_narratives", "events_referenced",
        "summary_brief", "summary_detailed", "summary_full", "claims",
        "catalysts_mentioned", "risks_mentioned",
    ],
    "properties": {
        "speaker": {"type": "string"},
        "category": {"type": "string"},
        "is_substantive": {"type": "boolean"},
        "overall_thesis": {"type": "string"},
        "sentiment": {"type": "string"},
        "conviction_score": {"type": "integer"},
        "risk_score": {"type": "integer"},
        "assets": {"type": "array", "items": {"type": "string"}},
        "key_tokens": {"type": "array", "items": {"type": "string"}},
        "narratives": {"type": "array", "items": {"type": "string"}},
        "key_narratives": {"type": "array", "items": {"type": "string"}},
        "events_referenced": {"type": "array", "items": {"type": "string"}},
        "summary_brief": {"type": "string"},
        "summary_detailed": {"type": "string"},
        "summary_full": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["claim_text", "type", "direction", "verbatim_quote", "timestamp"],
                "properties": {
                    "claim_text": {"type": "string"},
                    "type": {"type": "string"},
                    "asset": {"type": "string"},
                    "direction": {"type": "string"},
                    "target": {"type": "string"},
                    "timeframe": {"type": "string"},
                    "conditions": {"type": "string"},
                    "reasoning": {"type": "string"},
                    "evidence_cited": {"type": "array", "items": {"type": "string"}},
                    "conviction": {"type": "string"},
                    "verbatim_quote": {"type": "string"},
                    "timestamp": {"type": "string"},
                    "how_to_verify": {"type": "string"},
                },
            },
        },
        "catalysts_mentioned": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event": {"type": "string"},
                    "dateOrWindow": {"type": "string"},
                    "direction": {"type": "string"},
                    "description": {"type": "string"},
                },
            },
        },
        "risks_mentioned": {"type": "array", "items": {"type": "string"}},
    },
}


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
    """Extract one complete JSON object; do not repair incomplete model output."""
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


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _trim_text(value: Any, max_chars: int) -> str:
    text = value if isinstance(value, str) else ""
    text = text.strip()
    return text[:max_chars]


def _dedupe_keep_order(values: Iterable[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        key = json.dumps(value, sort_keys=True, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _string_list(values: Any, max_chars: int = 300) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text:
            result.append(text[:max_chars])
    return _dedupe_keep_order(result)


def _normalize_catalysts(values: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for value in values or []:
        if isinstance(value, dict):
            event = _trim_text(value.get("event") or value.get("name") or value.get("description"), 240)
            if not event:
                continue
            result.append({
                "event": event,
                "dateOrWindow": _trim_text(value.get("dateOrWindow") or value.get("timeframe"), 120),
                "direction": _trim_text(value.get("direction"), 40) or "neutral",
                "description": _trim_text(value.get("description") or event, 400),
            })
        else:
            event = _trim_text(value, 240)
            if event:
                result.append({
                    "event": event,
                    "dateOrWindow": "",
                    "direction": "neutral",
                    "description": event,
                })
    return _dedupe_keep_order(result)


def _chunk_transcript(transcript_text: str, max_chars: int) -> list[str]:
    max_chars = max(1, max_chars)
    lines = transcript_text.splitlines() or [transcript_text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        pieces = [line[i : i + max_chars] for i in range(0, len(line), max_chars)] or [line]
        for piece in pieces:
            piece_len = len(piece) + 1
            if current and current_len + piece_len > max_chars:
                chunks.append("\n".join(current).strip())
                current = []
                current_len = 0
            current.append(piece)
            current_len += piece_len

    if current:
        chunks.append("\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def _trim_claims(claims: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for claim in claims or []:
        if not isinstance(claim, dict):
            continue
        cleaned = dict(claim)
        cleaned["claim_text"] = _trim_text(cleaned.get("claim_text"), CLAIM_TEXT_MAX_CHARS)
        cleaned["verbatim_quote"] = _trim_text(cleaned.get("verbatim_quote"), QUOTE_MAX_CHARS)
        cleaned["reasoning"] = _trim_text(cleaned.get("reasoning"), 600)
        cleaned["how_to_verify"] = _trim_text(cleaned.get("how_to_verify"), 400)
        if not cleaned["claim_text"]:
            continue
        result.append(cleaned)
    return _dedupe_keep_order(result)


def _join_limited(parts: Iterable[Any], max_chars: int) -> str:
    text = "\n".join(str(part).strip() for part in parts if str(part or "").strip())
    if len(text) <= max_chars:
        return text

    # Do not leave a summary ending half-way through a sentence.  This covers the
    # usual English and Chinese sentence terminators.  An ellipsis is used only
    # when an unusually long sentence has no terminator inside the configured cap.
    prefix = text[:max_chars]
    boundaries = list(re.finditer(r"[.!?。！？]+(?:[\"'”’）\]\}]+)?", prefix))
    if boundaries:
        return prefix[: boundaries[-1].end()].rstrip()

    last_space = prefix.rfind(" ")
    if last_space > max_chars // 2:
        return prefix[:last_space].rstrip() + "…"
    return prefix.rstrip() + "…"


def _merge_analysis_payloads(payloads: list[Dict[str, Any]]) -> Dict[str, Any]:
    if not payloads:
        return {"is_substantive": False, "claims": []}

    substantive = [payload for payload in payloads if payload.get("is_substantive") is not False]
    if not substantive:
        merged = dict(payloads[0])
        merged["is_substantive"] = False
        merged["claims"] = []
        merged["chunk_count"] = len(payloads)
        return merged

    first = substantive[0]
    assets = _dedupe_keep_order(item for payload in substantive for item in (payload.get("assets") or payload.get("key_tokens") or []))
    narratives = _dedupe_keep_order(item for payload in substantive for item in (payload.get("narratives") or payload.get("key_narratives") or []))
    claims = _trim_claims(claim for payload in substantive for claim in (payload.get("claims") or []))

    merged: Dict[str, Any] = {
        "speaker": first.get("speaker"),
        "category": first.get("category"),
        "is_substantive": True,
        "overall_thesis": _join_limited((payload.get("overall_thesis") for payload in substantive), SUMMARY_BRIEF_MAX_CHARS),
        "sentiment": first.get("sentiment"),
        "conviction_score": first.get("conviction_score"),
        "risk_score": first.get("risk_score"),
        "assets": _string_list(assets, 80),
        "key_tokens": _string_list(assets, 80),
        "narratives": _string_list(narratives, 120),
        "key_narratives": _string_list(narratives, 120),
        "events_referenced": _string_list((item for payload in substantive for item in (payload.get("events_referenced") or [])), 240),
        "summary_brief": _join_limited((payload.get("summary_brief") or payload.get("overall_thesis") for payload in substantive), SUMMARY_BRIEF_MAX_CHARS),
        "summary_detailed": _join_limited((payload.get("summary_detailed") for payload in substantive), SUMMARY_DETAILED_MAX_CHARS),
        "summary_full": _join_limited((payload.get("summary_full") or payload.get("summary_detailed") for payload in substantive), SUMMARY_FULL_MAX_CHARS),
        "claims": claims,
        "catalysts_mentioned": _normalize_catalysts(item for payload in substantive for item in (payload.get("catalysts_mentioned") or [])),
        "risks_mentioned": _string_list((item for payload in substantive for item in (payload.get("risks_mentioned") or [])), 240),
        "chunk_count": len(payloads),
    }
    return merged


def _load_prompt() -> str:
    path = Path(__file__).parent.parent / "prompts" / "claim_analysis_prompt.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Claim analysis prompt not found at %s, using fallback", path)
        return (
            "Analyse the transcript chunk and output one JSON object with fields: speaker, "
            "category, is_substantive, overall_thesis, sentiment, assets, key_tokens, "
            "narratives, key_narratives, events_referenced, summary_brief, summary_detailed, "
            "summary_full, claims[], catalysts_mentioned[], risks_mentioned[]."
        )


@dataclass
class VideoAnalysisService:
    """Analyse a video from its stored transcript text (not by re-watching the video)."""

    settings: YouTubeCryptoSettings

    def analyze_video(
        self,
        video: YouTubeVideo,
        transcript_text: str,
        analysis_version: str,
    ) -> Optional[VideoAnalysis]:
        if not transcript_text or not transcript_text.strip():
            logger.warning("No transcript for video_id=%s; skipping analysis", video.video_id)
            return None

        chunks = _chunk_transcript(transcript_text, ANALYSIS_TRANSCRIPT_CHUNK_CHARS)
        start_time = time.perf_counter()
        payloads: list[Dict[str, Any]] = []
        prompt_tokens = cand_tokens = total_tokens = cached_tokens = 0

        for index, chunk in enumerate(chunks, start=1):
            prompt = self._build_prompt(video, chunk, index, len(chunks))
            try:
                full_text, usage = generate_text(
                    api_key=resolve_gemini_api_key(self.settings),
                    model=self.settings.gemini_model,
                    prompt=prompt,
                    max_output_tokens=ANALYSIS_MAX_OUTPUT_TOKENS,
                    temperature=0.1,
                    base_url=getattr(self.settings, "gemini_base_url", None),
                    response_mime_type="application/json",
                    response_schema=CLAIM_ANALYSIS_RESPONSE_SCHEMA,
                )
            except Exception:
                logger.exception(
                    "Error while calling Gemini for analysis video_id=%s chunk=%s/%s",
                    video.video_id,
                    index,
                    len(chunks),
                )
                raise

            try:
                chunk_payload = json.loads(_extract_first_json_object(full_text))
                payloads.append(chunk_payload)
                logger.info(
                    "analysis_chunk_done video_id=%s chunk=%s/%s claims=%s tokens=%s",
                    video.video_id,
                    index,
                    len(chunks),
                    len(chunk_payload.get("claims") or []),
                    usage.get("totalTokenCount") if usage else None,
                )
            except json.JSONDecodeError:
                logger.exception(
                    "Failed to parse analysis JSON for video_id=%s chunk=%s/%s. Text (truncated): %s",
                    video.video_id,
                    index,
                    len(chunks),
                    full_text[:2000],
                )
                raise

            if usage:
                prompt_tokens += usage.get("promptTokenCount") or 0
                cand_tokens += usage.get("candidatesTokenCount") or 0
                total_tokens += usage.get("totalTokenCount") or 0
                cached_tokens += usage.get("cachedContentTokenCount") or 0

            if index < len(chunks) and ANALYSIS_CHUNK_COOLDOWN_SECONDS > 0:
                time.sleep(ANALYSIS_CHUNK_COOLDOWN_SECONDS)

        elapsed_seconds = time.perf_counter() - start_time
        data = _merge_analysis_payloads(payloads)

        if data.get("is_substantive") is False:
            logger.info("Video %s flagged not substantive; skipping", video.video_id)
            return None

        assets = data.get("assets") or data.get("key_tokens") or []
        narratives = data.get("narratives") or data.get("key_narratives") or []
        summary_brief = data.get("summary_brief") or data.get("overall_thesis") or ""

        return VideoAnalysis(
            video_id=video.video_id,
            analysis_version=analysis_version,
            model_name=self.settings.gemini_model,
            summary_brief=summary_brief,
            summary_detailed=data.get("summary_detailed"),
            summary_full=data.get("summary_full"),
            transcript=None,
            sentiment=data.get("sentiment"),
            conviction_score=_safe_int(data.get("conviction_score")),
            risk_score=_safe_int(data.get("risk_score")),
            key_tokens=_string_list(assets, 80),
            key_narratives=_string_list(narratives, 120),
            speaker=data.get("speaker"),
            category=data.get("category"),
            is_substantive=data.get("is_substantive"),
            overall_thesis=data.get("overall_thesis"),
            claims=data.get("claims") or [],
            events_referenced=_string_list(data.get("events_referenced") or [], 240),
            catalysts_mentioned=_normalize_catalysts(data.get("catalysts_mentioned") or []),
            risks_mentioned=_string_list(data.get("risks_mentioned") or [], 240),
            raw_response=data,
            prompt_token_count=prompt_tokens or None,
            candidates_token_count=cand_tokens or None,
            total_token_count=total_tokens or None,
            cached_content_token_count=cached_tokens or None,
            elapsed_seconds=elapsed_seconds,
        )

    def _build_prompt(self, video: YouTubeVideo, transcript_text: str, chunk_index: int, total_chunks: int) -> str:
        base = _load_prompt()
        metadata = f"Video title: {video.title}\nChannel id: {video.channel_id}\n"
        if video.description:
            metadata += f"Description: {video.description[:1000]}\n"
        chunk_contract = (
            f"This is transcript chunk {chunk_index} of {total_chunks}. "
            f"Extract at most {CLAIM_ANALYSIS_MAX_CLAIMS_PER_CHUNK} highest-value claims from this chunk. "
            f"claim_text <= {CLAIM_TEXT_MAX_CHARS} chars; verbatim_quote <= {QUOTE_MAX_CHARS} chars; "
            f"summary_brief <= {SUMMARY_BRIEF_MAX_CHARS} chars; "
            f"summary_detailed <= {SUMMARY_DETAILED_PER_CHUNK_MAX_CHARS} chars; "
            f"summary_full <= {SUMMARY_FULL_PER_CHUNK_MAX_CHARS} chars."
        )
        return (
            f"{base}\n\n"
            f"--- VIDEO METADATA ---\n{metadata}\n"
            f"--- CHUNK CONTRACT ---\n{chunk_contract}\n"
            f"--- TRANSCRIPT CHUNK ---\n{transcript_text}"
        )
