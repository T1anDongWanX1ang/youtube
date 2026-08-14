import json
from typing import Optional

import aiomysql

from ..models.transcript import VideoTranscript

INSERT_SQL = """
    INSERT INTO youtube_crypto_video_transcripts (
        video_id,
        language,
        source,
        segments_json,
        full_text,
        word_count,
        duration_covered_sec,
        coverage_ok,
        model_name,
        prompt_token_count,
        candidates_token_count,
        total_token_count,
        elapsed_seconds,
        created_at,
        updated_at
    )
    VALUES (
        %s, %s, %s, %s, %s,
        %s, %s, %s,
        %s, %s, %s, %s,
        %s,
        NOW(), NOW()
    )
"""


def _insert_params(transcript: VideoTranscript) -> tuple:
    segments_json = json.dumps(transcript.segments) if transcript.segments is not None else None
    return (
        transcript.video_id,
        transcript.language,
        transcript.source,
        segments_json,
        transcript.full_text,
        transcript.word_count,
        transcript.duration_covered_sec,
        transcript.ok,
        transcript.model_name,
        transcript.prompt_token_count,
        transcript.candidates_token_count,
        transcript.total_token_count,
        transcript.elapsed_seconds,
    )


class TranscriptRepository:
    """Repository for youtube_crypto_video_transcripts table."""

    def __init__(self, db_pool: aiomysql.Pool):
        self.db_pool = db_pool

    async def upsert_transcript(self, transcript: VideoTranscript) -> None:
        """Insert a transcript row; ignore duplicates (one transcript per video_id)."""
        params = _insert_params(transcript)
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                try:
                    await cur.execute(INSERT_SQL, params)
                except Exception as e:  # noqa: BLE001 - tolerate duplicate-key only
                    msg = str(e)
                    if "Duplicate" not in msg and "PRIMARY" not in msg and "Unique" not in msg:
                        raise

    async def get_transcript(self, video_id: str) -> Optional[VideoTranscript]:
        sql = """
            SELECT video_id, language, source, segments_json, full_text,
                   word_count, duration_covered_sec, coverage_ok, model_name
            FROM youtube_crypto_video_transcripts
            WHERE video_id = %s
        """
        async with self.db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql, (video_id,))
                row = await cur.fetchone()

        if not row:
            return None

        seg = row.pop("segments_json", None)
        if isinstance(seg, (str, bytes)):
            try:
                row["segments"] = json.loads(seg)
            except json.JSONDecodeError:
                row["segments"] = []
        else:
            row["segments"] = seg or []

        ok = bool(row.pop("coverage_ok", False))
        return VideoTranscript(**row, ok=ok)
