import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from ..config.config import YouTubeCryptoSettings
from ..models import YouTubeVideo
from ..models.transcript import VideoTranscript
from ..utils.gemini_rest import generate_from_video
from ..utils.transcript_coverage import compute_coverage
from ..utils.transcript_parse import parse_segments

logger = logging.getLogger(__name__)

MIN_COVERAGE_RATIO = 0.9
MAX_CONTINUATIONS = 3
TRANSCRIBE_MAX_OUTPUT_TOKENS = 32768
TRANSCRIBE_MAX_DIRECT_VIDEO_SECONDS = int(os.getenv("YOUTUBE_TRANSCRIBE_MAX_DIRECT_VIDEO_SECONDS", "5400"))


def _nontranscribable_source(error: Exception) -> Optional[str]:
    """Return a terminal skip source for Gemini errors that cannot succeed on retry."""
    message = str(error).upper()
    if "RECITATION" in message:
        return "gemini_skipped_recitation"
    if (
        ("1,048,576" in message or "1048576" in message)
        and any(marker in message for marker in ("TOKEN", "INPUT", "CONTEXT"))
    ):
        return "gemini_skipped_input_too_large"
    return None


def _fmt_ts(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _extract_language(raw: str) -> Optional[str]:
    for line in (raw or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.upper().startswith("LANG:"):
            return stripped.split(":", 1)[1].strip() or None
        break
    return None


def _load_prompt() -> str:
    path = Path(__file__).parent.parent / "prompts" / "transcript_prompt.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Transcript prompt not found at %s, using fallback", path)
        return (
            "Transcribe the video verbatim. First line `LANG: <code>`. Then one line per "
            "segment starting with `[mm:ss]` (or `[hh:mm:ss]` past an hour). Do not "
            "translate, summarise, or skip anything."
        )


@dataclass
class TranscriptionService:
    """Transcribe a YouTube video to a verbatim, timestamped transcript via Gemini."""

    settings: YouTubeCryptoSettings

    def transcribe(self, video: YouTubeVideo) -> VideoTranscript:
        base_prompt = _load_prompt()
        model = getattr(self.settings, "transcription_model", None) or self.settings.gemini_model
        video_url = f"https://www.youtube.com/watch?v={video.video_id}"
        duration = video.duration_seconds or 0

        if duration > TRANSCRIBE_MAX_DIRECT_VIDEO_SECONDS:
            logger.warning(
                "Skipping direct Gemini video transcription for overlong video_id=%s duration=%ss limit=%ss",
                video.video_id,
                duration,
                TRANSCRIBE_MAX_DIRECT_VIDEO_SECONDS,
            )
            return VideoTranscript(
                video_id=video.video_id,
                full_text="",
                language=None,
                source="gemini_skipped_overlong",
                segments=[],
                word_count=0,
                duration_covered_sec=0,
                ok=False,
                model_name=model,
                elapsed_seconds=0.0,
            )

        segments: List[dict] = []
        language: Optional[str] = None
        last_covered = 0
        prompt_tokens = cand_tokens = total_tokens = 0
        start_time = time.perf_counter()

        for attempt in range(MAX_CONTINUATIONS + 1):
            if attempt == 0:
                prompt = base_prompt
            else:
                prompt = (
                    f"{base_prompt}\n\nResume the transcript from [{_fmt_ts(last_covered)}]. "
                    "Continue verbatim from there; do not repeat earlier content."
                )

            try:
                text, usage = generate_from_video(
                    api_key=self.settings.youtube_gemini_api_key,
                    model=model,
                    video_url=video_url,
                    prompt=prompt,
                    max_output_tokens=TRANSCRIBE_MAX_OUTPUT_TOKENS,
                    base_url=getattr(self.settings, "gemini_base_url", None),
                )
            except Exception as exc:
                skip_source = _nontranscribable_source(exc)
                if skip_source is None:
                    raise

                elapsed = time.perf_counter() - start_time
                coverage = compute_coverage(segments, duration, MIN_COVERAGE_RATIO)
                full_text = "\n".join(
                    f"[{_fmt_ts(segment['start'])}] {segment['text']}"
                    for segment in segments
                )
                logger.warning(
                    "Skipping non-transcribable video_id=%s source=%s error=%s",
                    video.video_id,
                    skip_source,
                    exc,
                )
                return VideoTranscript(
                    video_id=video.video_id,
                    full_text=full_text,
                    language=language,
                    source=skip_source,
                    segments=segments,
                    word_count=coverage["word_count"],
                    duration_covered_sec=coverage["duration_covered_sec"],
                    ok=False,
                    model_name=model,
                    prompt_token_count=prompt_tokens or None,
                    candidates_token_count=cand_tokens or None,
                    total_token_count=total_tokens or None,
                    elapsed_seconds=elapsed,
                )

            if attempt == 0:
                language = _extract_language(text)
            if usage:
                prompt_tokens += usage.get("promptTokenCount") or 0
                cand_tokens += usage.get("candidatesTokenCount") or 0
                total_tokens += usage.get("totalTokenCount") or 0

            parsed = parse_segments(text)
            new_segments = [s for s in parsed if s["start"] > last_covered] if attempt else parsed
            segments.extend(new_segments)

            coverage = compute_coverage(segments, duration, MIN_COVERAGE_RATIO)
            hit_output_limit = bool(usage and usage.get("finishReason") == "MAX_TOKENS")
            if coverage["ok"] and not hit_output_limit:
                break
            if coverage["duration_covered_sec"] <= last_covered:
                break
            last_covered = coverage["duration_covered_sec"]

        elapsed = time.perf_counter() - start_time
        coverage = compute_coverage(segments, duration, MIN_COVERAGE_RATIO)
        full_text = "\n".join(f"[{_fmt_ts(s['start'])}] {s['text']}" for s in segments)

        if not coverage["ok"]:
            logger.warning(
                "Transcript coverage insufficient for video_id=%s: covered=%ss duration=%ss words=%s",
                video.video_id,
                coverage["duration_covered_sec"],
                duration,
                coverage["word_count"],
            )

        return VideoTranscript(
            video_id=video.video_id,
            full_text=full_text,
            language=language,
            source="gemini",
            segments=segments,
            word_count=coverage["word_count"],
            duration_covered_sec=coverage["duration_covered_sec"],
            ok=coverage["ok"],
            model_name=model,
            prompt_token_count=prompt_tokens or None,
            candidates_token_count=cand_tokens or None,
            total_token_count=total_tokens or None,
            elapsed_seconds=elapsed,
        )
