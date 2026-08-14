from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class YouTubeChannel(BaseModel):
    """
    Domain model representing a monitored YouTube channel.
    """

    channel_id: str
    handle: Optional[str] = None
    title: str
    description: Optional[str] = None
    is_active: bool = True
    priority: int = 0
    subscriber_count: Optional[int] = None
    last_checked_at: Optional[datetime] = None
    last_video_published_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

