from datetime import datetime
from typing import List, Optional

import aiomysql
import json

from ..models import YouTubeVideo


class YouTubeVideoRepository:
    """
    Repository for youtube_crypto_videos table.
    """

    def __init__(self, db_pool: aiomysql.Pool):
        """
        Initialize repository with aiomysql connection pool.
        """
        self.db_pool = db_pool

    async def upsert_video(self, video: YouTubeVideo) -> None:
        """
        Insert a new video row if it does not exist.
        Existing rows are left unchanged to avoid overwriting analysis state.
        For Doris, we use a simple INSERT that relies on primary key uniqueness.
        """
        tags_json = json.dumps(video.tags) if video.tags is not None else None
        sql = """
            INSERT INTO youtube_crypto_videos (
                video_id,
                channel_id,
                title,
                description,
                published_at,
                thumbnail_url,
                duration_seconds,
                view_count,
                like_count,
                comment_count,
                tags,
                analysis_status,
                created_at,
                updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s,
                'pending',
                NOW(),
                NOW()
            )
        """
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                try:
                    await cur.execute(
                        sql,
                        (
                            video.video_id,
                            video.channel_id,
                            video.title,
                            video.description,
                            video.published_at,
                            video.thumbnail_url,
                            video.duration_seconds,
                            video.view_count,
                            video.like_count,
                            video.comment_count,
                            tags_json,
                        ),
                    )
                except Exception as e:
                    # Ignore duplicate key errors (video already exists)
                    if "Duplicate" not in str(e) and "PRIMARY" not in str(e):
                        raise

    async def get_pending_videos(self, limit: int) -> List[YouTubeVideo]:
        """
        Fetch retryable videos with complete transcripts, ordered by published_at ascending.
        """
        sql = """
            SELECT
                v.video_id,
                v.channel_id,
                c.title AS channel_title,
                v.title,
                v.description,
                v.published_at,
                v.thumbnail_url,
                v.duration_seconds,
                v.view_count,
                v.like_count,
                v.comment_count,
                v.tags
            FROM youtube_crypto_videos v
            LEFT JOIN youtube_crypto_channels c ON c.channel_id = v.channel_id
            INNER JOIN youtube_crypto_video_transcripts t ON t.video_id = v.video_id
            WHERE v.analysis_status IN ('pending', 'failed')
              AND t.coverage_ok = TRUE
            ORDER BY published_at ASC
            LIMIT %s
        """
        async with self.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql, (limit,))
                rows = await cur.fetchall()

        parsed_rows = []
        for row in rows:
            tags_val = row.get("tags")
            if isinstance(tags_val, (str, bytes)):
                try:
                    row["tags"] = json.loads(tags_val)
                except json.JSONDecodeError:
                    row["tags"] = None
            parsed_rows.append(YouTubeVideo(**row))

        return parsed_rows

    async def get_videos_needing_transcription(
        self, limit: int, lookback_days: int, max_attempts: int
    ) -> List[YouTubeVideo]:
        """
        Fetch retryable videos that do not yet have a transcript.

        The presence of a row in youtube_crypto_video_transcripts is the gate between the
        transcription stage and the analysis stage. This keeps the existing analysis_status
        state machine mostly untouched: new videos stay 'pending' through transcription, while
        old key-failure rows in 'failed' can be retried by the new value-gated workflow.
        """
        sql = """
            SELECT
                v.video_id,
                v.channel_id,
                c.title AS channel_title,
                c.priority AS channel_priority,
                v.title,
                v.description,
                v.published_at,
                v.thumbnail_url,
                v.duration_seconds,
                v.view_count,
                v.like_count,
                v.comment_count,
                v.tags
            FROM youtube_crypto_videos v
            LEFT JOIN youtube_crypto_channels c ON c.channel_id = v.channel_id
            LEFT JOIN youtube_crypto_video_transcripts t ON t.video_id = v.video_id
            WHERE v.analysis_status IN ('pending', 'failed')
              AND t.video_id IS NULL
              AND COALESCE(v.transcription_attempts, 0) < %s
              AND v.published_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            ORDER BY v.published_at DESC
            LIMIT %s
        """
        async with self.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql, (max_attempts, lookback_days, limit))
                rows = await cur.fetchall()

        parsed_rows = []
        for row in rows:
            tags_val = row.get("tags")
            if isinstance(tags_val, (str, bytes)):
                try:
                    row["tags"] = json.loads(tags_val)
                except json.JSONDecodeError:
                    row["tags"] = None
            parsed_rows.append(YouTubeVideo(**row))

        return parsed_rows

    async def count_transcripts_created_today(self) -> int:
        sql = """
            SELECT COUNT(*)
            FROM youtube_crypto_video_transcripts
            WHERE created_at >= CURDATE()
        """
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql)
                row = await cur.fetchone()
        return int(row[0] if row else 0)

    async def mark_skipped_low_value(self, video_id: str) -> None:
        sql = """
            UPDATE youtube_crypto_videos
            SET analysis_status = 'skipped_low_value',
                updated_at = NOW()
            WHERE video_id = %s
        """
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (video_id,))

    async def mark_in_progress(self, video_id: str) -> None:
        sql = """
            UPDATE youtube_crypto_videos
            SET analysis_status = 'in_progress',
                updated_at = NOW()
            WHERE video_id = %s
        """
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (video_id,))

    async def mark_completed(
        self,
        video_id: str,
        analysis_version: str,
        completed_at: Optional[datetime] = None,
    ) -> None:
        sql = """
            UPDATE youtube_crypto_videos
            SET
                analysis_status = 'completed',
                last_analysis_version = %s,
                last_analysis_at = COALESCE(%s, NOW()),
                updated_at = NOW()
            WHERE video_id = %s
        """
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (analysis_version, completed_at, video_id))

    async def mark_failed(self, video_id: str) -> None:
        sql = """
            UPDATE youtube_crypto_videos
            SET analysis_status = 'failed',
                updated_at = NOW()
            WHERE video_id = %s
        """
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (video_id,))

    async def record_transcription_failure(
        self, video_id: str, error: Exception, max_attempts: int
    ) -> None:
        """Record a retryable transcription failure and stop after the configured cap."""
        sql = """
            UPDATE youtube_crypto_videos
            SET
                transcription_attempts = COALESCE(transcription_attempts, 0) + 1,
                transcription_last_error = %s,
                transcription_last_failed_at = NOW(),
                analysis_status = CASE
                    WHEN COALESCE(transcription_attempts, 0) + 1 >= %s
                        THEN 'transcription_failed'
                    ELSE 'failed'
                END,
                updated_at = NOW()
            WHERE video_id = %s
        """
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (str(error)[:1000], max_attempts, video_id))

    async def mark_skipped_untranscribable(self, video_id: str, reason: str) -> None:
        """Prevent deterministic Gemini rejections from returning to the retry pool."""
        sql = """
            UPDATE youtube_crypto_videos
            SET
                analysis_status = 'skipped_untranscribable',
                transcription_last_error = %s,
                transcription_last_failed_at = NOW(),
                updated_at = NOW()
            WHERE video_id = %s
        """
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (reason[:1000], video_id))
