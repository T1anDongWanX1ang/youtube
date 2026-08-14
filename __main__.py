"""
YouTube Crypto Agent Entry Point

Run this module directly with:
    python -m youtube_crypto
"""

from .jobs.youtube_poll_job import run_polling_iteration
import logging
import asyncio
import time
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


async def _loop():
    poll_interval_seconds = 300
    logger.info(
        "Starting YouTube crypto polling loop with interval=%s seconds",
        poll_interval_seconds,
    )
    try:
        while True:
            start_ts = datetime.now(timezone.utc)
            logger.info("Starting polling iteration at %s", start_ts.isoformat())
            try:
                await run_polling_iteration()
            except Exception:
                logger.exception("Error during polling iteration")
            logger.info(
                "Polling iteration finished, sleeping for %s seconds",
                poll_interval_seconds,
            )
            await asyncio.sleep(poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, stopping polling loop")


def main() -> None:
    restart_delay_seconds = 10
    while True:
        try:
            asyncio.run(_loop())
            break
        except KeyboardInterrupt:
            logger.info("Received KeyboardInterrupt, stopping program")
            break
        except Exception:
            logger.exception(
                "Main process crashed unexpectedly; restarting after %s seconds",
                restart_delay_seconds,
            )
            time.sleep(restart_delay_seconds)
            logger.info("Restarting main loop")


if __name__ == "__main__":
    main()
