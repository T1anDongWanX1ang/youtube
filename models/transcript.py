from typing import List, Optional

from pydantic import BaseModel, Field


class VideoTranscript(BaseModel):
    """Verbatim, timestamped transcript for a single video.

    Aligned with the youtube_crypto_video_transcripts table. Decoupled from VideoAnalysis
    so analysis always reads a complete source-of-truth.
    """

    video_id: str
    full_text: str

    language: Optional[str] = None
    source: str = "gemini"
    segments: List[dict] = Field(default_factory=list)  # [{"start": <sec:int>, "text": str}]

    # Coverage metrics
    word_count: Optional[int] = None
    duration_covered_sec: Optional[int] = None
    ok: bool = False

    # LLM call metadata
    model_name: Optional[str] = None
    prompt_token_count: Optional[int] = None
    candidates_token_count: Optional[int] = None
    total_token_count: Optional[int] = None
    elapsed_seconds: Optional[float] = None
