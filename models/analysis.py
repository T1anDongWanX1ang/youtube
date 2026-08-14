from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class VideoAnalysis(BaseModel):
    """
    Structured analysis result for a single video, aligned with
    youtube_crypto_video_analyses table.
    """

    video_id: str
    analysis_version: str
    model_name: str

    # Summaries
    summary_brief: str
    summary_detailed: Optional[str] = None
    summary_full: Optional[str] = None

    # Verbatim transcript in the video's original language (Gemini output)
    transcript: Optional[str] = None

    # Scores / sentiment
    sentiment: Optional[str] = None
    conviction_score: Optional[int] = None
    risk_score: Optional[int] = None

    # Tags
    key_tokens: Optional[List[str]] = None
    key_narratives: Optional[List[str]] = None

    # Claim-level analysis (new). Legacy fields above stay populated for backward compat
    # (the consumer's facts.consensus module reads sentiment / summaries / tokens).
    speaker: Optional[str] = None
    category: Optional[str] = None
    is_substantive: Optional[bool] = None
    overall_thesis: Optional[str] = None
    claims: Optional[List[Dict[str, Any]]] = None
    events_referenced: Optional[List[str]] = None
    catalysts_mentioned: Optional[List[Dict[str, Any]]] = None
    risks_mentioned: Optional[List[str]] = None

    # Raw response
    raw_response: Optional[Dict[str, Any]] = None

    # Token usage
    prompt_token_count: Optional[int] = None
    candidates_token_count: Optional[int] = None
    total_token_count: Optional[int] = None
    cached_content_token_count: Optional[int] = None

    # Timing
    elapsed_seconds: Optional[float] = None

    # Metadata (usually DB-managed)
    created_at: Optional[datetime] = None


