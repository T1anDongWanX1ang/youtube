import json

import aiomysql

from ..models import VideoAnalysis

INSERT_SQL = """
    INSERT INTO youtube_crypto_video_analyses (
        video_id,
        analysis_version,
        model_name,
        summary_brief,
        summary_detailed,
        summary_full,
        transcript,
        sentiment,
        conviction_score,
        risk_score,
        key_tokens,
        key_narratives,
        speaker,
        category,
        is_substantive,
        overall_thesis,
        claims_json,
        events_referenced_json,
        catalysts_json,
        risks_json,
        raw_response,
        prompt_token_count,
        candidates_token_count,
        total_token_count,
        cached_content_token_count,
        elapsed_seconds,
        created_at
    )
    VALUES (
        %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s,
        %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s,
        %s, %s, %s, %s,
        %s,
        NOW()
    )
"""


def _js(value):
    return json.dumps(value) if value is not None else None


def _insert_params(analysis: VideoAnalysis) -> tuple:
    return (
        analysis.video_id,
        analysis.analysis_version,
        analysis.model_name,
        analysis.summary_brief,
        analysis.summary_detailed,
        analysis.summary_full,
        analysis.transcript,
        analysis.sentiment,
        analysis.conviction_score,
        analysis.risk_score,
        _js(analysis.key_tokens),
        _js(analysis.key_narratives),
        analysis.speaker,
        analysis.category,
        analysis.is_substantive,
        analysis.overall_thesis,
        _js(analysis.claims),
        _js(analysis.events_referenced),
        _js(analysis.catalysts_mentioned),
        _js(analysis.risks_mentioned),
        _js(analysis.raw_response),
        analysis.prompt_token_count,
        analysis.candidates_token_count,
        analysis.total_token_count,
        analysis.cached_content_token_count,
        analysis.elapsed_seconds,
    )


class VideoAnalysisRepository:
    """Repository for youtube_crypto_video_analyses table."""

    def __init__(self, db_pool: aiomysql.Pool):
        self.db_pool = db_pool

    async def insert_analysis(self, analysis: VideoAnalysis) -> None:
        """Insert a new analysis row for a video; tolerate a prior successful write.

        The polling process can be interrupted after the analysis row is written but
        before the video status is marked completed.  Treat that retry as idempotent
        so the status transition and downstream viewpoint stage can still finish.
        """
        params = _insert_params(analysis)
        async with self.db_pool.acquire() as conn:
            async with conn.cursor() as cur:
                try:
                    await cur.execute(INSERT_SQL, params)
                except Exception as exc:  # noqa: BLE001 - only duplicate keys are safe
                    message = str(exc)
                    if "Duplicate" not in message and "PRIMARY" not in message and "Unique" not in message:
                        raise
