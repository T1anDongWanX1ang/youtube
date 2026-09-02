import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

import requests

from ..config.config import MIN_DURATION_SECONDS
from ..models import YouTubeVideo

logger = logging.getLogger(__name__)


YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"
_KEY_UNAVAILABLE_REASONS = {
    "quotaExceeded",
    "dailyLimitExceeded",
    "userRateLimitExceeded",
    "keyInvalid",
    "ipRefererBlocked",
    "accessNotConfigured",
}


def _parse_rfc3339(dt_str: str) -> datetime:
    """
    Parse a RFC3339 datetime string (e.g. 2024-01-01T12:34:56Z) to aware datetime.
    """
    if not dt_str:
        raise ValueError("Empty datetime string")
    # Replace trailing Z with +00:00 for fromisoformat compatibility
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    return datetime.fromisoformat(dt_str)


def _parse_duration_iso8601(duration: str) -> Optional[int]:
    """
    Parse an ISO8601 duration string (e.g. PT1H2M3S) to seconds.
    Returns None if parsing fails.
    """
    if not duration:
        return None

    # Very small, dependency-free parser for YouTube durations
    # Format: PnDTnHnMnS (we only care about H/M/S)
    import re

    pattern = re.compile(
        r"^P"
        r"(?:(?P<days>\d+)D)?"
        r"(?:T"
        r"(?:(?P<hours>\d+)H)?"
        r"(?:(?P<minutes>\d+)M)?"
        r"(?:(?P<seconds>\d+)S)?"
        r")?$"
    )
    match = pattern.match(duration)
    if not match:
        return None

    parts = match.groupdict()
    days = int(parts.get("days") or 0)
    hours = int(parts.get("hours") or 0)
    minutes = int(parts.get("minutes") or 0)
    seconds = int(parts.get("seconds") or 0)
    total_seconds = days * 86400 + hours * 3600 + minutes * 60 + seconds
    return total_seconds


@dataclass
class YouTubeFetchService:
    """
    Thin wrapper around YouTube Data API v3 for:
    - resolving a channel's uploads playlist
    - listing recent uploads within a time window
    - fetching video details for those uploads
    """

    api_key: str
    fallback_api_keys: Sequence[str] = ()

    def __post_init__(self) -> None:
        self._api_keys = tuple(
            key for key in (self.api_key, *self.fallback_api_keys) if key
        )
        if not self._api_keys:
            raise ValueError("At least one YouTube Data API key is required")
        self._active_key_index = 0

    @staticmethod
    def _key_unavailable_reason(response: requests.Response) -> Optional[str]:
        """Return a safe reason when a response is specific to this API key."""
        if response.status_code not in (400, 401, 403):
            return None
        try:
            error = response.json().get("error", {})
            errors = error.get("errors") or []
        except ValueError:
            return None

        for item in errors:
            reason = str(item.get("reason") or "")
            if reason in _KEY_UNAVAILABLE_REASONS:
                return reason

        message = str(error.get("message") or "").lower()
        if "api key" in message and ("invalid" in message or "not valid" in message):
            return "keyInvalid"
        return None

    def _get(self, path: str, params: Dict[str, str], timeout: int) -> requests.Response:
        """GET with failover for quota, rate-limit, and invalid-key responses."""
        last_response: Optional[requests.Response] = None
        key_count = len(self._api_keys)
        for offset in range(key_count):
            key_index = (self._active_key_index + offset) % key_count
            api_key = self._api_keys[key_index]
            request_params = {**params, "key": api_key}
            response = requests.get(f"{YOUTUBE_API_BASE}{path}", params=request_params, timeout=timeout)
            unavailable_reason = self._key_unavailable_reason(response)
            if unavailable_reason is None:
                self._active_key_index = key_index
                return response

            last_response = response
            if offset < key_count - 1:
                logger.warning(
                    "YouTube Data API key %d/%d is unavailable (%s); switching to the next key",
                    key_index + 1,
                    key_count,
                    unavailable_reason,
                )

        assert last_response is not None
        return last_response

    def resolve_channel_id_from_handle(self, handle: str) -> str:
        """
        Resolve a YouTube channel ID (UC...) from a channel handle.

        This uses the channels.list endpoint with the `forHandle` parameter.
        """
        if not handle:
            raise ValueError("Handle is required to resolve channel_id")

        normalized = handle.lstrip("@")

        params = {
            "part": "id",
            "forHandle": normalized,
        }
        resp = self._get("/channels", params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        items = data.get("items") or []
        if not items:
            raise ValueError(f"No channel found for handle={normalized}")

        channel_id = items[0].get("id")
        if not channel_id:
            raise ValueError(f"Missing id for handle={normalized}")

        return channel_id

    def get_channel_image_from_handle(self, handle: str) -> str:
        """Return the preferred YouTube-hosted avatar URL for a channel handle."""
        if not handle:
            raise ValueError("Handle is required to fetch a channel image")

        resp = self._get(
            "/channels",
            {"part": "snippet", "forHandle": handle.lstrip("@")},
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("items") or []
        if not items:
            raise ValueError(f"No channel found for handle={handle.lstrip('@')}")

        thumbnails = (items[0].get("snippet") or {}).get("thumbnails") or {}
        for size in ("maxres", "standard", "high", "medium", "default"):
            image_url = (thumbnails.get(size) or {}).get("url")
            if image_url:
                return image_url
        raise ValueError(f"No channel image found for handle={handle.lstrip('@')}")

    def get_uploads_playlist_id(self, channel_id: str) -> str:
        """
        Use channels.list to get the uploads playlist ID for a channel.
        """
        params = {
            "part": "contentDetails",
            "id": channel_id,
        }
        resp = self._get("/channels", params, timeout=10)
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            logger.error(
                "YouTube channels.list(contentDetails) failed for channel_id=%s, "
                "status=%s, body=%s",
                channel_id,
                resp.status_code,
                resp.text,
            )
            raise
        data = resp.json()

        items = data.get("items") or []
        if not items:
            raise ValueError(f"No channel found for channel_id={channel_id}")

        content_details = items[0].get("contentDetails") or {}
        related_playlists = content_details.get("relatedPlaylists") or {}
        uploads_playlist_id = related_playlists.get("uploads")
        if not uploads_playlist_id:
            raise ValueError(f"Channel {channel_id} has no uploads playlist")

        return uploads_playlist_id

    def get_channel_subscriber_count(self, channel_id: str) -> Optional[int]:
        """
        Fetch the subscriber count for a channel using channels.list statistics.
        """
        if not channel_id:
            raise ValueError("channel_id is required to fetch subscriber count")

        params = {
            "part": "statistics",
            "id": channel_id,
        }
        resp = self._get("/channels", params, timeout=10)
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            logger.error(
                "YouTube channels.list(statistics) failed for channel_id=%s, "
                "status=%s, body=%s",
                channel_id,
                resp.status_code,
                resp.text,
            )
            raise
        data = resp.json()

        items = data.get("items") or []
        if not items:
            raise ValueError(f"No channel found for channel_id={channel_id}")

        statistics = items[0].get("statistics") or {}
        raw_subs = statistics.get("subscriberCount")
        try:
            return int(raw_subs) if raw_subs is not None else None
        except (TypeError, ValueError):
            logger.warning(
                "Invalid subscriberCount=%r for channel_id=%s", raw_subs, channel_id
            )
            return None

    def list_uploads_video_ids(self, uploads_playlist_id: str, days: int) -> List[str]:
        """
        List video IDs from a channel's uploads playlist within the last N days.

        The YouTube API returns items in order: newest -> oldest. We preserve this
        order and stop once we hit videos older than the cutoff.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        video_ids: List[str] = []
        page_token: Optional[str] = None

        while True:
            params = {
                "part": "contentDetails,snippet",
                "playlistId": uploads_playlist_id,
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token

            resp = self._get("/playlistItems", params, timeout=15)
            try:
                resp.raise_for_status()
            except requests.HTTPError:
                logger.error(
                    "YouTube playlistItems.list failed for playlist_id=%s, "
                    "status=%s, body=%s",
                    uploads_playlist_id,
                    resp.status_code,
                    resp.text,
                )
                raise
            data = resp.json()

            items = data.get("items") or []
            for item in items:
                content_details = item.get("contentDetails") or {}
                snippet = item.get("snippet") or {}

                published_str = content_details.get("videoPublishedAt") or snippet.get(
                    "publishedAt"
                )
                if not published_str:
                    continue

                published_dt = _parse_rfc3339(published_str)

                if published_dt >= cutoff:
                    vid = content_details.get("videoId")
                    if vid:
                        video_ids.append(vid)
                else:
                    # Remaining items and pages will be older; stop early.
                    return video_ids

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return video_ids

    def fetch_recent_videos(self, video_ids: List[str]) -> List[YouTubeVideo]:
        """
        Fetch details for a collection of video IDs and filter out
        very short videos (duration < MIN_DURATION_SECONDS).
        """
        if not video_ids:
            return []

        videos: List[YouTubeVideo] = []
        # YouTube API allows up to 50 IDs per request
        batch_size = 50

        for i in range(0, len(video_ids), batch_size):
            batch_ids = video_ids[i : i + batch_size]
            params = {
                "part": "snippet,contentDetails,statistics",
                "id": ",".join(batch_ids),
            }
            resp = self._get("/videos", params, timeout=15)
            try:
                resp.raise_for_status()
            except requests.HTTPError:
                logger.error(
                    "YouTube videos.list failed for batch_ids=%s, status=%s, body=%s",
                    ",".join(batch_ids),
                    resp.status_code,
                    resp.text,
                )
                raise
            data = resp.json()

            for item in data.get("items") or []:
                vid = item.get("id")
                snippet = item.get("snippet") or {}
                content_details = item.get("contentDetails") or {}
                statistics = item.get("statistics") or {}
                tags = snippet.get("tags") or []

                duration_str = content_details.get("duration")
                duration_seconds = _parse_duration_iso8601(duration_str)

                # Filter by minimum duration
                if duration_seconds is not None and duration_seconds < MIN_DURATION_SECONDS:
                    continue

                published_str = snippet.get("publishedAt")
                if not published_str or not vid:
                    continue

                video_url = f"https://www.youtube.com/watch?v={vid}"

                published_at = _parse_rfc3339(published_str)
                thumbnails = snippet.get("thumbnails") or {}
                default_thumb = thumbnails.get("high") or thumbnails.get("medium") or thumbnails.get("default") or {}
                thumbnail_url = default_thumb.get("url")

                # Log tags and video URL for verification/debugging
                logger.info(
                    "YouTube video fetched: id=%s url=%s tags=%s",
                    vid,
                    video_url,
                    tags,
                )

                video = YouTubeVideo(
                    video_id=vid,
                    channel_id=snippet.get("channelId") or "",
                    title=snippet.get("title") or "",
                    description=snippet.get("description"),
                    published_at=published_at,
                    thumbnail_url=thumbnail_url,
                    duration_seconds=duration_seconds,
                    view_count=int(statistics.get("viewCount")) if statistics.get("viewCount") is not None else None,
                    like_count=int(statistics.get("likeCount")) if statistics.get("likeCount") is not None else None,
                    comment_count=int(statistics.get("commentCount")) if statistics.get("commentCount") is not None else None,
                    tags=tags or None,
                )
                videos.append(video)

        return videos
