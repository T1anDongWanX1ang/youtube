from datetime import datetime
from typing import List, Optional

import aiomysql

from ..models import YouTubeChannel


class YouTubeChannelRepository:
    """
    Repository for youtube_crypto_channels table.
    """

    def __init__(self, db_pool: aiomysql.Pool):
        """
        Initialize repository with aiomysql connection pool.
        """
        self.db_pool = db_pool

    async def get_active_channels(self) -> List[YouTubeChannel]:
        """
        Fetch all active channels ordered by priority (desc) then channel_id.
        """
        sql = """
            SELECT
                channel_id,
                handle,
                title,
                description,
                is_active,
                priority,
                subscriber_count,
                last_checked_at,
                last_video_published_at,
                created_at,
                updated_at
            FROM youtube_crypto_channels
            WHERE is_active = 1
            ORDER BY priority DESC, channel_id ASC
        """
        async with self.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql)
                rows = await cur.fetchall()
        
        # Convert MySQL TINYINT(1) to bool for is_active field
        channels = []
        for row in rows:
            row_dict = dict(row)
            if "is_active" in row_dict:
                row_dict["is_active"] = bool(row_dict["is_active"])
            channels.append(YouTubeChannel(**row_dict))
        return channels

    async def update_channel_id(self, old_channel_id: str, new_channel_id: str) -> None:
        """
        Replace a channel row's primary key channel_id with a new value.

        Doris unique tables do not allow updating key columns directly, so this
        is implemented as delete-then-insert: the existing row is read, deleted,
        and re-inserted under the new channel_id (preserving all other columns,
        with updated_at refreshed to NOW()).

        Note: this does not update any existing youtube_crypto_videos rows that
        may reference the old channel_id. At the current stage this agent is
        typically used before videos are populated, but if needed this can be
        extended to keep videos in sync.
        """
        if old_channel_id == new_channel_id:
            return

        select_sql = """
            SELECT
                channel_id,
                handle,
                title,
                description,
                is_active,
                priority,
                subscriber_count,
                last_checked_at,
                last_video_published_at,
                created_at,
                updated_at
            FROM youtube_crypto_channels
            WHERE channel_id = %s
        """
        delete_sql = "DELETE FROM youtube_crypto_channels WHERE channel_id = %s"
        insert_sql = """
            INSERT INTO youtube_crypto_channels (
                channel_id,
                handle,
                title,
                description,
                is_active,
                priority,
                subscriber_count,
                last_checked_at,
                last_video_published_at,
                created_at,
                updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """
        async with self.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(select_sql, (old_channel_id,))
                row = await cur.fetchone()
                if row is None:
                    return

                await cur.execute(delete_sql, (old_channel_id,))
                await cur.execute(
                    insert_sql,
                    (
                        new_channel_id,
                        row["handle"],
                        row["title"],
                        row["description"],
                        row["is_active"],
                        row["priority"],
                        row["subscriber_count"],
                        row["last_checked_at"],
                        row["last_video_published_at"],
                        row["created_at"],
                    ),
                )

    async def update_poll_state(
        self,
        channel_id: str,
        last_checked_at: datetime,
        last_video_published_at: Optional[datetime],
        subscriber_count: Optional[int] = None,
    ) -> None:
        """
        Update polling state for a channel after a fetch run.
        """
        sql = """
            UPDATE youtube_crypto_channels
            SET
                last_checked_at = %s,
                last_video_published_at = COALESCE(%s, last_video_published_at),
                subscriber_count = COALESCE(%s, subscriber_count),
                updated_at = NOW()
            WHERE channel_id = %s
        """
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    sql,
                    (
                        last_checked_at,
                        last_video_published_at,
                        subscriber_count,
                        channel_id,
                    ),
                )
