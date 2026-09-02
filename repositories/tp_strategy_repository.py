"""Mirror YouTube research data into the TP Strategy MySQL database."""

import json
from typing import Any

import aiomysql

from ..models import ResearchViewpoint


class TpStrategyRepository:
    """Persistence methods for tables consumed by TP Strategy.

    The target database is independent from the polling database, so each write
    is an idempotent upsert rather than part of a cross-database transaction.
    """

    _CHANNEL_TABLE_DDL = """
        CREATE TABLE IF NOT EXISTS youtube_crypto_channels (
            channel_id VARCHAR(255) NOT NULL PRIMARY KEY,
            handle VARCHAR(255) NOT NULL,
            title VARCHAR(500) NOT NULL,
            description TEXT NULL,
            is_active TINYINT NOT NULL DEFAULT 1,
            priority SMALLINT NULL DEFAULT 0,
            subscriber_count BIGINT NULL,
            last_checked_at DATETIME NULL,
            last_video_published_at DATETIME NULL,
            created_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
            channel_image TEXT NULL
        ) CHARACTER SET utf8mb4
    """

    def __init__(self, db_pool: aiomysql.Pool):
        self.db_pool = db_pool

    async def upsert_viewpoints(self, viewpoints: list[ResearchViewpoint]) -> None:
        """Write extracted viewpoints to ``tp_strategy.research_viewpoint``."""
        if not viewpoints:
            return
        sql = """
            INSERT INTO research_viewpoint (
                viewpoint_id, source_type, source_id, source_url,
                source_author_id, source_author_handle, source_author_display_name,
                source_published_at, captured_at, speaker_handle, title,
                core_judgment, subject, follow_up, market_id, judgment_quotes,
                fact_basis, reasoning, conditions, time_window, uncertainty,
                counterpoints, falsification, missing_context, updated_at, synced_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s,
                %s, %s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
            ) AS new_row ON DUPLICATE KEY UPDATE
                source_type = new_row.source_type,
                source_id = new_row.source_id,
                source_url = new_row.source_url,
                source_author_id = new_row.source_author_id,
                source_author_handle = new_row.source_author_handle,
                source_author_display_name = new_row.source_author_display_name,
                source_published_at = new_row.source_published_at,
                speaker_handle = new_row.speaker_handle,
                title = new_row.title,
                core_judgment = new_row.core_judgment,
                subject = new_row.subject,
                follow_up = new_row.follow_up,
                judgment_quotes = new_row.judgment_quotes,
                fact_basis = new_row.fact_basis,
                reasoning = new_row.reasoning,
                conditions = new_row.conditions,
                time_window = new_row.time_window,
                uncertainty = new_row.uncertainty,
                counterpoints = new_row.counterpoints,
                falsification = new_row.falsification,
                missing_context = new_row.missing_context,
                updated_at = NOW(),
                synced_at = NOW()
        """
        params = [self._viewpoint_params(item) for item in viewpoints]
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(sql, params)

    async def sync_channels(self, channels: list[dict[str, Any]]) -> None:
        """Create the target channel table when needed and upsert all source rows."""
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                      AND table_name = 'youtube_crypto_channels'
                    LIMIT 1
                    """
                )
                if await cur.fetchone() is None:
                    await cur.execute(self._CHANNEL_TABLE_DDL)
                if not channels:
                    return
                await cur.executemany(
                    """
                    INSERT INTO youtube_crypto_channels (
                        channel_id, handle, title, description, is_active, priority,
                        subscriber_count, last_checked_at, last_video_published_at,
                        created_at, updated_at, channel_image
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    ) AS new_row ON DUPLICATE KEY UPDATE
                        handle = new_row.handle,
                        title = new_row.title,
                        description = new_row.description,
                        is_active = new_row.is_active,
                        priority = new_row.priority,
                        subscriber_count = new_row.subscriber_count,
                        last_checked_at = new_row.last_checked_at,
                        last_video_published_at = new_row.last_video_published_at,
                        created_at = new_row.created_at,
                        updated_at = new_row.updated_at,
                        channel_image = new_row.channel_image
                    """,
                    [
                        (
                            item["channel_id"],
                            item["handle"],
                            item["title"],
                            item.get("description"),
                            int(bool(item["is_active"])),
                            item.get("priority"),
                            item.get("subscriber_count"),
                            item.get("last_checked_at"),
                            item.get("last_video_published_at"),
                            item.get("created_at"),
                            item.get("updated_at"),
                            item.get("channel_image"),
                        )
                        for item in channels
                    ],
                )

    @staticmethod
    def _viewpoint_params(item: ResearchViewpoint) -> tuple[Any, ...]:
        return (
            item.viewpoint_id,
            item.source_type,
            item.source_id,
            item.source_url,
            item.source_author_id,
            item.source_author_handle,
            item.source_author_display_name,
            item.source_published_at,
            item.speaker_handle,
            item.title,
            item.core_judgment,
            item.subject,
            item.follow_up,
            json.dumps(item.judgment_quotes, ensure_ascii=False),
            json.dumps(item.fact_basis, ensure_ascii=False),
            json.dumps(item.reasoning, ensure_ascii=False),
            json.dumps(item.conditions, ensure_ascii=False),
            json.dumps(item.time_window, ensure_ascii=False),
            json.dumps(item.uncertainty, ensure_ascii=False),
            json.dumps(item.counterpoints, ensure_ascii=False),
            json.dumps(item.falsification, ensure_ascii=False),
            json.dumps(item.missing_context, ensure_ascii=False),
        )
