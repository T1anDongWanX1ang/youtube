from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ResearchViewpoint(BaseModel):
    """One independently actionable opinion extracted from a YouTube analysis."""

    viewpoint_id: str = Field(default_factory=lambda: str(uuid4()))
    source_type: str = "Youtube"
    source_id: str
    source_url: str
    source_author_id: str
    source_author_handle: str
    source_author_display_name: str | None = None
    source_published_at: datetime
    speaker_handle: str
    title: str
    core_judgment: str
    subject: str
    follow_up: str
    judgment_quotes: list[str] = Field(default_factory=list)
    fact_basis: list[Any] = Field(default_factory=list)
    reasoning: list[Any] = Field(default_factory=list)
    conditions: list[Any] = Field(default_factory=list)
    time_window: dict[str, str] = Field(
        default_factory=lambda: {"text": "", "source_quote": ""}
    )
    uncertainty: dict[str, str] = Field(
        default_factory=lambda: {"text": "", "source_quote": ""}
    )
    counterpoints: list[Any] = Field(default_factory=list)
    falsification: list[Any] = Field(default_factory=list)
    missing_context: list[str] = Field(default_factory=list)
