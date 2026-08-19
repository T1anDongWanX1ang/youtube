"""On-demand single-video processing: URL -> transcript -> claims.

Reuses the existing fetch / transcribe / analyze services so an operator can
extract one YouTube video on demand (via the web endpoint) instead of waiting
for the polling job. The repository writes are best-effort: a failed upsert must
not lose the extracted claims the caller asked for.
"""

import asyncio
import inspect
import logging
from typing import Any, Callable, Dict, Optional

from ..config.config import YouTubeCryptoSettings
from ..jobs.youtube_poll_job import ANALYSIS_VERSION
from ..repositories import TranscriptRepository, VideoAnalysisRepository
from ..services.analysis_service import VideoAnalysisService
from ..services.transcription_service import TranscriptionService
from ..services.youtube_fetch_service import YouTubeFetchService
from ..utils.url import extract_video_id

logger = logging.getLogger(__name__)

__all__ = ["ANALYSIS_VERSION", "process_one"]

# Lazily-created, process-lifetime aiomysql pool shared across requests. Behind the
# FastAPI endpoint, process_one runs once per HTTP request; creating a fresh pool
# (up to db_max_pool_size connections) each time would leak connections and exhaust
# the DB. Mirror the polling job's singleton-pool pattern instead.
_db_pool: Optional[Any] = None
_db_pool_lock = asyncio.Lock()


async def _get_db_pool() -> Any:
    """Return a cached aiomysql pool, creating it once on first use."""
    global _db_pool
    if _db_pool is None:
        async with _db_pool_lock:
            # Re-check inside the lock: another coroutine may have created it while
            # we awaited the lock.
            if _db_pool is None:
                settings = YouTubeCryptoSettings.from_env()
                _db_pool = await settings.create_db_pool()
                logger.info("process_one DB pool created")
    return _db_pool


def _reset_db_pool_cache() -> None:
    """Drop the cached pool reference (test hook; does not close the pool)."""
    global _db_pool
    _db_pool = None


async def _maybe_await(value: Any) -> Any:
    """Await ``value`` if it is awaitable, otherwise return it as-is.

    The injected fakes may be sync or async, and the real repository writes are
    async (aiomysql). This lets the same call site handle both.
    """
    if inspect.isawaitable(value):
        return await value
    return value


async def _build_real_deps() -> Dict[str, Callable[..., Any]]:
    settings = YouTubeCryptoSettings.from_env()
    pool = await _get_db_pool()

    fetch_service = YouTubeFetchService(
        api_key=settings.youtube_data_api_keys[0],
        fallback_api_keys=settings.youtube_data_api_keys[1:],
    )
    transcription_service = TranscriptionService(settings=settings)
    analysis_service = VideoAnalysisService(settings=settings)
    transcript_repo = TranscriptRepository(pool)
    analysis_repo = VideoAnalysisRepository(pool)

    return {
        "fetch": fetch_service.fetch_recent_videos,
        "transcribe": transcription_service.transcribe,
        "analyze": analysis_service.analyze_video,
        "upsert_tx": transcript_repo.upsert_transcript,
        "insert_an": analysis_repo.insert_analysis,
    }


async def process_one(url: str, *, _deps: Optional[Dict[str, Callable[..., Any]]] = None) -> dict:
    """Extract a single YouTube video into structured evidence.

    Pipeline: extract_video_id -> fetch metadata -> transcribe -> (best-effort)
    persist transcript -> analyze claims -> (best-effort) persist analysis.

    ``_deps`` is a test seam: a dict with keys ``fetch``, ``transcribe``,
    ``analyze``, ``upsert_tx``, ``insert_an``. Each value may be sync or async.
    When ``_deps`` is None, real services/repositories are built from env config.
    """
    video_id = extract_video_id(url)

    deps = _deps if _deps is not None else await _build_real_deps()

    videos = await _maybe_await(deps["fetch"]([video_id]))
    if not videos:
        raise RuntimeError(f"no video metadata found for video_id={video_id}")
    video = videos[0]

    transcript = await _maybe_await(deps["transcribe"](video))
    if transcript is None or not transcript.ok or not (transcript.full_text or "").strip():
        raise RuntimeError(f"transcript not available for video_id={video_id}")

    # Best-effort transcript persistence; do not fail the request on a DB error.
    try:
        await _maybe_await(deps["upsert_tx"](transcript))
    except Exception:
        logger.exception("Failed to upsert transcript for video_id=%s", video_id)

    analysis = await _maybe_await(
        deps["analyze"](video, transcript.full_text, ANALYSIS_VERSION)
    )

    claims = []
    if analysis is not None:
        claims = analysis.claims or []
        # Best-effort analysis persistence; the caller still gets the claims back.
        try:
            await _maybe_await(deps["insert_an"](analysis))
        except Exception:
            logger.exception("Failed to insert analysis for video_id=%s", video_id)

    published_at = getattr(video, "published_at", None)
    return {
        "video_id": video.video_id,
        "title": video.title,
        "channel_title": video.channel_title,
        "published_at": published_at.isoformat() if published_at else None,
        "claims_json": {"claims": claims},
    }
