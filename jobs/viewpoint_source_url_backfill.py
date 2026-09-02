"""Make existing YouTube viewpoint URLs unique for predx_news deduplication."""

import argparse
import asyncio
import logging
from collections import defaultdict
from itertools import islice

import aiomysql

from ..config.config import YouTubeCryptoSettings
from ..utils.viewpoint_url import with_viewpoint_ordinal

logger = logging.getLogger(__name__)

_UPDATE_BATCH_SIZE = 500


async def _planned_updates(pool: aiomysql.Pool) -> list[tuple[str, str]]:
    """Return ``(viewpoint_id, new_source_url)`` ordered deterministically."""
    sql = """
        SELECT viewpoint_id, source_id, source_url
        FROM research_viewpoint
        WHERE source_type = 'Youtube'
        ORDER BY source_id ASC, viewpoint_id ASC
    """
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql)
            rows = await cur.fetchall()

    ordinals: defaultdict[str, int] = defaultdict(int)
    updates: list[tuple[str, str]] = []
    for row in rows:
        source_id = row["source_id"]
        ordinals[source_id] += 1
        new_url = with_viewpoint_ordinal(row["source_url"], ordinals[source_id])
        if new_url != row["source_url"]:
            updates.append((row["viewpoint_id"], new_url))
    return updates


async def _apply_updates(
    pool: aiomysql.Pool,
    updates: list[tuple[str, str]],
    *,
    mirror: bool,
    dry_run: bool,
) -> int:
    if not updates:
        return 0
    if dry_run:
        return len(updates)

    synced_at = ", synced_at = NOW()" if mirror else ""
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            update_iterator = iter(updates)
            while batch := list(islice(update_iterator, _UPDATE_BATCH_SIZE)):
                case_sql = " ".join("WHEN %s THEN %s" for _ in batch)
                ids_sql = ", ".join("%s" for _ in batch)
                sql = f"""
                    UPDATE research_viewpoint
                    SET source_url = CASE viewpoint_id {case_sql} ELSE source_url END,
                        updated_at = NOW(){synced_at}
                    WHERE source_type = 'Youtube'
                      AND viewpoint_id IN ({ids_sql})
                """
                params = [
                    parameter
                    for viewpoint_id, url in batch
                    for parameter in (viewpoint_id, url)
                ] + [viewpoint_id for viewpoint_id, _ in batch]
                await cur.execute(sql, params)
    return len(updates)


async def backfill_viewpoint_source_urls(*, dry_run: bool = False) -> dict[str, int]:
    """Backfill the source database and configured TP Strategy mirror.

    Each database is read independently so a previously partial run is safe to
    re-run.  The mapping is stable because rows are ordered by source and ID.
    """
    settings = YouTubeCryptoSettings.from_env()
    source_pool = await settings.create_db_pool()
    mirror_pool = (
        await settings.create_tp_strategy_db_pool() if settings.tp_strategy_enabled else None
    )
    result = {"source": 0, "tp_strategy": 0}
    try:
        source_updates = await _planned_updates(source_pool)
        result["source"] = await _apply_updates(
            source_pool, source_updates, mirror=False, dry_run=dry_run
        )
        if mirror_pool is not None:
            mirror_updates = await _planned_updates(mirror_pool)
            result["tp_strategy"] = await _apply_updates(
                mirror_pool, mirror_updates, mirror=True, dry_run=dry_run
            )
        logger.info("Viewpoint source URL backfill result: %s", result)
        return result
    finally:
        source_pool.close()
        await source_pool.wait_closed()
        if mirror_pool is not None:
            mirror_pool.close()
            await mirror_pool.wait_closed()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report rows without updating them")
    args = parser.parse_args()
    result = asyncio.run(backfill_viewpoint_source_urls(dry_run=args.dry_run))
    print(
        "viewpoint_source_url_backfill "
        f"source={result['source']} tp_strategy={result['tp_strategy']} dry_run={args.dry_run}"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    main()
