from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class YouTubeVideo(BaseModel):
    """
    Domain model representing a YouTube video and its metadata.
    """

    video_id: str
    channel_id: str
    channel_title: Optional[str] = None
    title: str
    description: Optional[str] = None
    published_at: datetime
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[int] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    tags: Optional[List[str]] = None
