"""Backfill ``youtube_crypto_channels.channel_image`` from YouTube handles.

Run from the repository root:
    uv run python -m youtube_crypto.jobs.channel_image_backfill
"""

import argparse
import asyncio
import logging

from ..config.config import YouTubeCryptoSettings
from ..repositories import TpStrategyRepository, YouTubeChannelRepository
from ..services import YouTubeFetchService

logger = logging.getLogger(__name__)


async def backfill_channel_images(*, limit: int | None = None) -> tuple[int, int]:
    """Backfill channel images and return ``(updated, failed)`` counts."""
    settings = YouTubeCryptoSettings.from_env()
    db_pool = await settings.create_db_pool()
    tp_strategy_pool = (
        await settings.create_tp_strategy_db_pool() if settings.tp_strategy_enabled else None
    )
    try:
        repository = YouTubeChannelRepository(db_pool)
        fetch_service = YouTubeFetchService(
            api_key=settings.youtube_data_api_keys[0],
            fallback_api_keys=settings.youtube_data_api_keys[1:],
        )
        channels = await repository.get_channels_missing_channel_image(limit=limit)
        updated = 0
        failed = 0

        for channel in channels:
            channel_id = channel["channel_id"]
            handle = channel["handle"]
            try:
                channel_image = fetch_service.get_channel_image_from_handle(handle)
                if await repository.update_channel_image(channel_id, channel_image):
                    updated += 1
                    logger.info("Stored channel image for handle=%s", handle)
            except Exception:
                failed += 1
                logger.exception("Could not fetch channel image for handle=%s", handle)

        logger.info(
            "Channel image backfill complete: selected=%d updated=%d failed=%d",
            len(channels),
            updated,
            failed,
        )
        if tp_strategy_pool is not None:
            mirror = TpStrategyRepository(tp_strategy_pool)
            channels_for_sync = await repository.get_all_channels_for_sync()
            await mirror.sync_channels(channels_for_sync)
            logger.info("Mirrored %d YouTube channels to TP Strategy", len(channels_for_sync))
        return updated, failed
    finally:
        db_pool.close()
        await db_pool.wait_closed()
        if tp_strategy_pool is not None:
            tp_strategy_pool.close()
            await tp_strategy_pool.wait_closed()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill YouTube channel avatar URLs.")
    parser.add_argument("--limit", type=int, help="Process at most this many missing rows.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(backfill_channel_images(limit=args.limit))


if __name__ == "__main__":
    main()
