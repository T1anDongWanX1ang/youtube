"""Backfill opinion-level viewpoints from completed YouTube analyses."""

import argparse
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from ..config.config import YouTubeCryptoSettings
from ..models import YouTubeVideo
from ..repositories import ResearchViewpointRepository
from ..services import ViewpointExtractionService

logger = logging.getLogger(__name__)


async def run_viewpoint_backfill(analysis_date: date) -> tuple[int, int]:
    """Process unhandled analyses for one UTC date; returns (videos, viewpoints)."""
    settings = YouTubeCryptoSettings.from_env()
    pool = await settings.create_db_pool()
    try:
        repository = ResearchViewpointRepository(pool)
        extractor = ViewpointExtractionService(settings=settings)
        rows = await repository.get_unprocessed_analyses_for_date(analysis_date)
        viewpoint_count = 0
        for row in rows:
            video = YouTubeVideo(
                video_id=row["video_id"],
                channel_id=row["channel_id"],
                channel_title=row.get("channel_title"),
                title=row["title"],
                published_at=row["published_at"],
            )
            drafts = extractor.extract(row["summary_detailed"], video.video_id)
            viewpoints = repository.build_viewpoints(
                video=video,
                channel_handle=row.get("handle"),
                channel_title=row.get("channel_title"),
                drafts=drafts,
            )
            await repository.insert_viewpoints(viewpoints)
            viewpoint_count += len(viewpoints)
            logger.info(
                "Backfilled %d viewpoints for video_id=%s",
                len(viewpoints),
                video.video_id,
            )
        return len(rows), viewpoint_count
    finally:
        pool.close()
        await pool.wait_closed()


async def _run_batched_viewpoint_backfill(
    *,
    after: datetime,
    before: datetime,
    batch_size: int,
) -> tuple[int, int, int]:
    """Backfill a fixed analysis-created-at range.

    Each successful source is made durable immediately.  The keyset cursor avoids
    holding all historical summaries in memory and allows a later invocation to
    resume from the remaining sources after an interruption.
    """
    settings = YouTubeCryptoSettings.from_env()
    pool = await settings.create_db_pool()
    videos = viewpoints = failures = 0
    last_created_at: datetime | None = None
    last_video_id: str | None = None
    try:
        repository = ResearchViewpointRepository(pool)
        extractor = ViewpointExtractionService(settings=settings)
        while True:
            rows = await repository.get_unprocessed_analyses_batch(
                after=after,
                before=before,
                after_created_at=last_created_at,
                after_video_id=last_video_id,
                limit=batch_size,
            )
            if not rows:
                break
            for row in rows:
                # Advance first so a bad model response does not stall this run.
                last_created_at = row["analysis_created_at"]
                last_video_id = row["video_id"]
                video = YouTubeVideo(
                    video_id=row["video_id"],
                    channel_id=row["channel_id"],
                    channel_title=row.get("channel_title"),
                    title=row["title"],
                    published_at=row["published_at"],
                )
                try:
                    drafts = extractor.extract(row["summary_detailed"], video.video_id)
                    items = repository.build_viewpoints(
                        video=video,
                        channel_handle=row.get("handle"),
                        channel_title=row.get("channel_title"),
                        drafts=drafts,
                    )
                    await repository.insert_viewpoints(items)
                    videos += 1
                    viewpoints += len(items)
                except Exception:
                    failures += 1
                    logger.exception("Historical viewpoint extraction failed video_id=%s", video.video_id)
            logger.info(
                "Historical viewpoint backfill progress videos=%d viewpoints=%d failures=%d last=%s",
                videos,
                viewpoints,
                failures,
                last_video_id,
            )
        return videos, viewpoints, failures
    finally:
        pool.close()
        await pool.wait_closed()


async def run_all_viewpoint_backfill(batch_size: int = 100) -> tuple[int, int, int]:
    """Backfill every analysis present when the run starts."""
    return await _run_batched_viewpoint_backfill(
        after=datetime(1970, 1, 1),
        before=datetime.now(timezone.utc).replace(tzinfo=None),
        batch_size=batch_size,
    )


async def run_recent_viewpoint_backfill(
    days: int, batch_size: int = 100
) -> tuple[int, int, int]:
    """Backfill unprocessed analyses created in the previous number of days."""
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    after = before - timedelta(days=days)
    return await _run_batched_viewpoint_backfill(
        after=after,
        before=before,
        batch_size=batch_size,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--date", type=date.fromisoformat)
    group.add_argument("--all", action="store_true")
    group.add_argument("--days", type=int)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    if args.all:
        videos, viewpoints, failures = asyncio.run(
            run_all_viewpoint_backfill(batch_size=max(1, args.batch_size))
        )
        print(
            f"backfill_all videos={videos} viewpoints={viewpoints} failures={failures}"
        )
    elif args.days is not None:
        videos, viewpoints, failures = asyncio.run(
            run_recent_viewpoint_backfill(max(1, args.days), batch_size=max(1, args.batch_size))
        )
        print(
            f"backfill_days={args.days} videos={videos} viewpoints={viewpoints} failures={failures}"
        )
    else:
        videos, viewpoints = asyncio.run(run_viewpoint_backfill(args.date))
        print(f"backfill_date={args.date.isoformat()} videos={videos} viewpoints={viewpoints}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    main()
