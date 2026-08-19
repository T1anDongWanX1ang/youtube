"""
YouTube Crypto Agent - Polling Job

This job:
1) Loads configuration and DB connection.
2) Fetches recent uploads for each active channel via YouTube Data API v3.
3) Inserts any new videos into youtube_crypto_videos (status = 'pending').
4) Runs Gemini analysis for a small batch of pending videos and stores results.
"""

import logging
from datetime import datetime, timezone

from ..config.config import (
    ANALYSIS_BATCH_SIZE,
    YouTubeCryptoSettings,
)
from ..repositories import (
    TranscriptRepository,
    VideoAnalysisRepository,
    ResearchViewpointRepository,
    YouTubeChannelRepository,
    YouTubeVideoRepository,
)
from ..services import (
    TranscriptionService,
    VideoAnalysisService,
    ViewpointExtractionService,
    VideoValueDecision,
    YouTubeFetchService,
    score_video_for_analysis,
    select_videos_for_analysis,
)

logger = logging.getLogger(__name__)


ANALYSIS_VERSION = "youtube_crypto_v2_flashlite_claims_2026"


def _select_transcription_candidates(
    videos,
    *,
    limit: int,
) -> list[VideoValueDecision]:
    return select_videos_for_analysis(videos, limit=limit)


def _remaining_transcription_capacity(
    *,
    processed_today: int,
    daily_limit: int,
    batch_size: int,
) -> int:
    return max(0, min(batch_size, daily_limit - processed_today))


async def _get_db_pool():
    """
    Lazily create and cache an aiomysql pool using YouTubeCryptoSettings.
    """
    # Simple module-level cache to avoid recreating pools in the loop.
    if not hasattr(_get_db_pool, "_pool"):
        settings = YouTubeCryptoSettings.from_env()
        _get_db_pool._pool = await settings.create_db_pool()  # type: ignore[attr-defined]
        logger.info("YouTube Crypto DB pool created")
    return _get_db_pool._pool  # type: ignore[attr-defined]


async def _persist_viewpoints(
    *,
    video,
    analysis,
    channel_repo: YouTubeChannelRepository,
    viewpoint_repo: ResearchViewpointRepository,
    viewpoint_service: ViewpointExtractionService,
) -> None:
    """Best-effort opinion extraction after a completed video analysis."""
    if not analysis.summary_detailed or await viewpoint_repo.has_youtube_viewpoints(video.video_id):
        return
    handle, channel_title = await channel_repo.get_channel_identity(video.channel_id)
    drafts = viewpoint_service.extract(analysis.summary_detailed, video.video_id)
    viewpoints = viewpoint_repo.build_viewpoints(
        video=video,
        channel_handle=handle,
        channel_title=channel_title,
        drafts=drafts,
    )
    await viewpoint_repo.insert_viewpoints(viewpoints)
    logger.info("Stored %d viewpoints for video_id=%s", len(viewpoints), video.video_id)


async def run_polling_iteration() -> None:
    """
    Single polling iteration:
    - Discover recent videos and upsert into youtube_crypto_videos
    - Analyze pending videos with Gemini
    - Persist analysis results
    """
    settings = YouTubeCryptoSettings.from_env()
    db_pool = await _get_db_pool()

    channel_repo = YouTubeChannelRepository(db_pool)
    video_repo = YouTubeVideoRepository(db_pool)
    analysis_repo = VideoAnalysisRepository(db_pool)
    viewpoint_repo = ResearchViewpointRepository(db_pool)
    transcript_repo = TranscriptRepository(db_pool)
    fetch_service = YouTubeFetchService(
        api_key=settings.youtube_data_api_keys[0],
        fallback_api_keys=settings.youtube_data_api_keys[1:],
    )
    analysis_service = VideoAnalysisService(settings=settings)
    viewpoint_service = ViewpointExtractionService(settings=settings)
    transcription_service = TranscriptionService(settings=settings)

    now = datetime.now(timezone.utc)

    # Do not make already-ready results wait for the channel crawl (which can take
    # several minutes across all configured channels).
    pending_videos = await video_repo.get_pending_videos(limit=ANALYSIS_BATCH_SIZE)
    logger.info("Found %d already-ready videos for priority analysis", len(pending_videos))
    for video in pending_videos:
        transcript = await transcript_repo.get_transcript(video.video_id)
        if transcript is None or not transcript.ok:
            continue

        logger.info("Analyzing already-ready video_id=%s", video.video_id)
        await video_repo.mark_in_progress(video.video_id)
        try:
            analysis = analysis_service.analyze_video(
                video=video,
                transcript_text=transcript.full_text,
                analysis_version=ANALYSIS_VERSION,
            )
            if analysis is None:
                await video_repo.mark_completed(
                    video_id=video.video_id,
                    analysis_version=ANALYSIS_VERSION,
                    completed_at=datetime.now(timezone.utc),
                )
                continue
            await analysis_repo.insert_analysis(analysis)
            try:
                await _persist_viewpoints(
                    video=video,
                    analysis=analysis,
                    channel_repo=channel_repo,
                    viewpoint_repo=viewpoint_repo,
                    viewpoint_service=viewpoint_service,
                )
            except Exception:
                logger.exception("Viewpoint extraction failed for video_id=%s", video.video_id)
            await video_repo.mark_completed(
                video_id=video.video_id,
                analysis_version=ANALYSIS_VERSION,
                completed_at=datetime.now(timezone.utc),
            )
        except Exception:
            logger.exception("Priority analysis failed for video_id=%s", video.video_id)
            await video_repo.mark_failed(video.video_id)

    # Phase 1: Discover recent videos for each active channel
    channels = await channel_repo.get_active_channels()
    logger.info("Found %d active YouTube channels", len(channels))

    for channel in channels:
        subscriber_count: int | None = None

        # Resolve real YouTube channel_id if we only have a handle or a non-UC id
        resolved_channel_id = channel.channel_id
        if (not resolved_channel_id) or not resolved_channel_id.startswith("UC"):
            handle_or_id = channel.handle or resolved_channel_id
            if not handle_or_id:
                logger.warning(
                    "Channel %s has neither valid channel_id nor handle, skipping",
                    channel.title,
                )
                continue

            try:
                resolved_channel_id = fetch_service.resolve_channel_id_from_handle(
                    handle_or_id
                )
                # Backfill channel_id into DB so future runs don't need to resolve again
                await channel_repo.update_channel_id(
                    old_channel_id=channel.channel_id,
                    new_channel_id=resolved_channel_id,
                )
                logger.info(
                    "Resolved channel_id for %s: %s -> %s",
                    channel.title,
                    channel.channel_id,
                    resolved_channel_id,
                )
            except Exception:
                logger.exception(
                    "Failed to resolve channel_id from handle=%s for title=%s",
                    handle_or_id,
                    channel.title,
                )
                continue

        # Fetch channel-level statistics (subscriber count snapshot)
        try:
            subscriber_count = fetch_service.get_channel_subscriber_count(
                resolved_channel_id
            )
            logger.info(
                "Channel stats for %s (%s): subscriber_count=%s",
                channel.title,
                resolved_channel_id,
                subscriber_count,
            )
        except Exception:
            logger.exception(
                "Failed to fetch channel statistics for channel_id=%s",
                resolved_channel_id,
            )

        try:
            uploads_playlist_id = fetch_service.get_uploads_playlist_id(resolved_channel_id)
            logger.info(
                "Resolved uploads playlist for channel %s (%s): %s",
                channel.title,
                resolved_channel_id,
                uploads_playlist_id,
            )
        except Exception:
            logger.exception(
                "Failed to resolve uploads playlist for channel_id=%s",
                resolved_channel_id,
            )
            continue

        try:
            video_ids = fetch_service.list_uploads_video_ids(
                uploads_playlist_id=uploads_playlist_id,
                days=settings.lookback_days,
            )
            logger.info(
                "Channel %s (%s) has %d recent uploads in last %d days",
                channel.title,
                resolved_channel_id,
                len(video_ids),
                settings.lookback_days,
            )
        except Exception:
            logger.exception(
                "Failed to list uploads for channel_id=%s", resolved_channel_id
            )
            continue

        try:
            videos = fetch_service.fetch_recent_videos(video_ids)
            logger.info(
                "Fetched %d videos with sufficient duration for channel %s (%s)",
                len(videos),
                channel.title,
                resolved_channel_id,
            )
        except Exception:
            logger.exception(
                "Failed to fetch video details for channel_id=%s", resolved_channel_id
            )
            continue

        if not videos:
            await channel_repo.update_poll_state(
                channel_id=resolved_channel_id,
                last_checked_at=now,
                last_video_published_at=channel.last_video_published_at,
                subscriber_count=subscriber_count,
            )
            continue

        latest_published_at = channel.last_video_published_at

        for video in videos:
            try:
                await video_repo.upsert_video(video)
            except Exception:
                logger.exception(
                    "Failed to upsert video_id=%s for channel_id=%s",
                    video.video_id,
                    channel.channel_id,
                )
            # Compare datetimes safely - normalize both to aware datetimes
            video_published = video.published_at
            if video_published.tzinfo is None:
                video_published = video_published.replace(tzinfo=timezone.utc)
            
            if latest_published_at is None:
                latest_published_at = video_published
            else:
                # Normalize latest_published_at if it's naive
                latest_ts = latest_published_at
                if latest_ts.tzinfo is None:
                    latest_ts = latest_ts.replace(tzinfo=timezone.utc)
                
                if video_published > latest_ts:
                    latest_published_at = video_published

        await channel_repo.update_poll_state(
            channel_id=resolved_channel_id,
            last_checked_at=now,
            last_video_published_at=latest_published_at,
            subscriber_count=subscriber_count,
        )

    # Phase 1.5: Transcribe pending videos that do not have a transcript yet.
    # A complete transcript is the source-of-truth the analysis stage reads, so capture it
    # first (and validate coverage inside the service) before any analysis happens.
    candidate_videos = await video_repo.get_videos_needing_transcription(
        limit=settings.transcribe_batch_size * settings.transcribe_candidate_pool_multiplier,
        lookback_days=settings.lookback_days,
        max_attempts=settings.transcribe_max_attempts,
    )
    processed_today = await video_repo.count_transcripts_created_today()
    remaining_capacity = _remaining_transcription_capacity(
        processed_today=processed_today,
        daily_limit=settings.daily_transcribe_limit,
        batch_size=settings.transcribe_batch_size,
    )
    if remaining_capacity <= 0:
        logger.info(
            "Daily transcription limit reached: processed_today=%s daily_limit=%s",
            processed_today,
            settings.daily_transcribe_limit,
        )
        selected_decisions = []
    else:
        selected_decisions = _select_transcription_candidates(
            candidate_videos,
            limit=remaining_capacity,
        )
    selected_ids = {item.video.video_id for item in selected_decisions}
    skipped_decisions = [
        score_video_for_analysis(video)
        for video in candidate_videos
        if video.video_id not in selected_ids
    ]
    logger.info(
        "Found %d transcription candidates in %d days; selected %d high-value videos",
        len(candidate_videos),
        settings.lookback_days,
        len(selected_decisions),
    )
    for decision in skipped_decisions:
        if decision.decision == "skip":
            logger.info(
                "Skipping low-value video_id=%s score=%s reason=%s title=%s",
                decision.video.video_id,
                decision.score,
                decision.reason,
                decision.video.title,
            )
            await video_repo.mark_skipped_low_value(decision.video.video_id)

    for decision in selected_decisions:
        video = decision.video
        try:
            transcript = transcription_service.transcribe(video)
            await transcript_repo.upsert_transcript(transcript)
            if transcript.source.startswith("gemini_skipped_"):
                await video_repo.mark_skipped_untranscribable(
                    video.video_id,
                    transcript.source,
                )
                logger.info(
                    "Marked video_id=%s as untranscribable source=%s",
                    video.video_id,
                    transcript.source,
                )
                continue
            logger.info(
                "Transcribed video_id=%s score=%s reason=%s ok=%s covered=%ss words=%s",
                video.video_id,
                decision.score,
                decision.reason,
                transcript.ok,
                transcript.duration_covered_sec,
                transcript.word_count,
            )
        except Exception as exc:
            logger.exception("Transcription failed for video_id=%s", video.video_id)
            await video_repo.record_transcription_failure(
                video.video_id,
                exc,
                settings.transcribe_max_attempts,
            )

    # Phase 2: Run claim-level analysis for pending videos that have a complete transcript.
    # Analysis reads the stored transcript text (no second video watch, no router pass).
    pending_videos = await video_repo.get_pending_videos(limit=ANALYSIS_BATCH_SIZE)
    logger.info("Found %d pending videos for analysis", len(pending_videos))

    for video in pending_videos:
        transcript = await transcript_repo.get_transcript(video.video_id)
        if transcript is None:
            # Not transcribed yet; the transcription stage will handle it on a later pass.
            continue
        if not transcript.ok:
            logger.info(
                "Video_id=%s has an incomplete transcript; skipping analysis", video.video_id
            )
            continue

        logger.info("Analyzing video_id=%s", video.video_id)
        await video_repo.mark_in_progress(video.video_id)

        try:
            analysis = analysis_service.analyze_video(
                video=video,
                transcript_text=transcript.full_text,
                analysis_version=ANALYSIS_VERSION,
            )
            if analysis is None:
                logger.info(
                    "Video_id=%s skipped (not substantive)", video.video_id
                )
                await video_repo.mark_completed(
                    video_id=video.video_id,
                    analysis_version=ANALYSIS_VERSION,
                    completed_at=datetime.now(timezone.utc),
                )
                continue

            await analysis_repo.insert_analysis(analysis)
            try:
                await _persist_viewpoints(
                    video=video,
                    analysis=analysis,
                    channel_repo=channel_repo,
                    viewpoint_repo=viewpoint_repo,
                    viewpoint_service=viewpoint_service,
                )
            except Exception:
                logger.exception("Viewpoint extraction failed for video_id=%s", video.video_id)
            await video_repo.mark_completed(
                video_id=video.video_id,
                analysis_version=ANALYSIS_VERSION,
                completed_at=datetime.now(timezone.utc),
            )
        except Exception:
            logger.exception("Analysis failed for video_id=%s", video.video_id)
            await video_repo.mark_failed(video.video_id)
