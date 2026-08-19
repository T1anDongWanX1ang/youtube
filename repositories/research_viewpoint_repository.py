"""Persistence and backfill queries for YouTube opinion-level viewpoints."""

import json
from datetime import date, datetime
from typing import Any

import aiomysql

from ..models import ResearchViewpoint, YouTubeVideo
from ..services.viewpoint_extraction_service import ViewpointDraft


class ResearchViewpointRepository:
    def __init__(self, db_pool: aiomysql.Pool):
        self.db_pool = db_pool

    async def has_youtube_viewpoints(self, video_id: str) -> bool:
        sql = """
            SELECT 1 FROM research_viewpoint
            WHERE source_type = 'Youtube' AND source_id = %s
            LIMIT 1
        """
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (video_id,))
                return await cur.fetchone() is not None

    async def get_unprocessed_analyses_for_date(self, analysis_date: date) -> list[dict[str, Any]]:
        sql = """
            SELECT a.video_id, a.summary_detailed, v.channel_id, v.title,
                   v.published_at, c.handle, c.title AS channel_title
            FROM youtube_crypto_video_analyses a
            INNER JOIN youtube_crypto_videos v ON v.video_id = a.video_id
            LEFT JOIN youtube_crypto_channels c ON c.channel_id = v.channel_id
            LEFT JOIN research_viewpoint r
              ON r.source_type = 'Youtube' AND r.source_id = a.video_id
            WHERE DATE(a.created_at) = %s
              AND r.source_id IS NULL
              AND a.summary_detailed IS NOT NULL
              AND a.summary_detailed <> ''
            ORDER BY a.created_at ASC
        """
        async with self.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql, (analysis_date,))
                return list(await cur.fetchall())

    async def get_unprocessed_analyses_batch(
        self,
        *,
        after: datetime,
        before: datetime,
        after_created_at: datetime | None,
        after_video_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Read one stable, keyset-paginated batch for the all-history backfill."""
        sql = """
            SELECT a.video_id, a.summary_detailed, a.created_at AS analysis_created_at,
                   v.channel_id, v.title, v.published_at, c.handle,
                   c.title AS channel_title
            FROM youtube_crypto_video_analyses a
            INNER JOIN youtube_crypto_videos v ON v.video_id = a.video_id
            LEFT JOIN youtube_crypto_channels c ON c.channel_id = v.channel_id
            LEFT JOIN research_viewpoint r
              ON r.source_type = 'Youtube' AND r.source_id = a.video_id
            WHERE r.source_id IS NULL
              AND a.summary_detailed IS NOT NULL
              AND a.summary_detailed <> ''
              AND a.created_at >= %s
              AND a.created_at <= %s
              AND (
                %s IS NULL
                OR a.created_at > %s
                OR (a.created_at = %s AND a.video_id > %s)
              )
            ORDER BY a.created_at ASC, a.video_id ASC
            LIMIT %s
        """
        async with self.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    sql,
                    (
                        after,
                        before,
                        after_created_at,
                        after_created_at,
                        after_created_at,
                        after_video_id,
                        limit,
                    ),
                )
                return list(await cur.fetchall())

    async def insert_viewpoints(self, viewpoints: list[ResearchViewpoint]) -> None:
        if not viewpoints:
            return
        sql = """
            INSERT INTO research_viewpoint (
                viewpoint_id, source_type, source_id, source_url,
                source_author_id, source_author_handle, source_author_display_name,
                source_published_at, captured_at, speaker_handle, title,
                core_judgment, subject, follow_up, market_id, judgment_quotes,
                fact_basis, reasoning, conditions, time_window, uncertainty,
                counterpoints, falsification, missing_context, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s,
                %s, %s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
            )
        """
        params = [
            (
                item.viewpoint_id, item.source_type, item.source_id, item.source_url,
                item.source_author_id, item.source_author_handle,
                item.source_author_display_name, item.source_published_at,
                item.speaker_handle, item.title, item.core_judgment, item.subject,
                item.follow_up, json.dumps(item.judgment_quotes, ensure_ascii=False),
                json.dumps(item.fact_basis, ensure_ascii=False),
                json.dumps(item.reasoning, ensure_ascii=False),
                json.dumps(item.conditions, ensure_ascii=False),
                json.dumps(item.time_window, ensure_ascii=False),
                json.dumps(item.uncertainty, ensure_ascii=False),
                json.dumps(item.counterpoints, ensure_ascii=False),
                json.dumps(item.falsification, ensure_ascii=False),
                json.dumps(item.missing_context, ensure_ascii=False),
            )
            for item in viewpoints
        ]
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(sql, params)

    @staticmethod
    def build_viewpoints(
        *,
        video: YouTubeVideo,
        channel_handle: str | None,
        channel_title: str | None,
        drafts: list[ViewpointDraft],
    ) -> list[ResearchViewpoint]:
        publisher = (channel_handle or channel_title or video.channel_title or video.channel_id).strip()
        display_name = (channel_title or video.channel_title or publisher).strip()
        return [
            ResearchViewpoint(
                source_id=video.video_id,
                source_url=f"https://www.youtube.com/watch?v={video.video_id}",
                source_author_id=video.channel_id,
                source_author_handle=publisher[:200],
                source_author_display_name=display_name[:256],
                source_published_at=video.published_at,
                speaker_handle=publisher[:200],
                title=draft.title,
                core_judgment=draft.core_judgment,
                subject=draft.subject,
                follow_up=draft.follow_up,
                missing_context=[
                    "Extracted from youtube_crypto_video_analyses.summary_detailed."
                ],
            )
            for draft in drafts
        ]
