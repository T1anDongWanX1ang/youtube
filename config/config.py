from pathlib import Path

import aiomysql
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class YouTubeCryptoSettings(BaseSettings):
    """
    Configuration for the YouTube Crypto agent.

    Configuration loaded from environment variables.
    """

    youtube_data_api_key: str = Field(..., alias="YOUTUBE_DATA_API_KEY")
    youtube_gemini_api_key: str = Field(..., alias="YOUTUBE_GEMINI_API_KEY")

    # Database configuration
    database_url: str = Field(..., alias="DATABASE_URL")
    db_min_pool_size: int = Field(default=2, alias="DB_MIN_POOL_SIZE")
    db_max_pool_size: int = Field(default=10, alias="DB_MAX_POOL_SIZE")

    # Gemini model to use for claim extraction. Keep the default cheap because this
    # worker runs continuously; override via YOUTUBE_GEMINI_MODEL when needed.
    gemini_model: str = Field(default="gemini-2.5-flash-lite", alias="YOUTUBE_GEMINI_MODEL")

    # Model used for the transcription stage. Overridable via YOUTUBE_TRANSCRIBE_MODEL.
    transcription_model: str = Field(
        default="gemini-2.5-flash-lite", alias="YOUTUBE_TRANSCRIBE_MODEL"
    )

    # Base URL for the Gemini REST API. Override to point at a Gemini-native proxy
    # (e.g. https://api.rcouyi.com) for local testing with a third-party key.
    gemini_base_url: str = Field(
        default="https://generativelanguage.googleapis.com",
        alias="YOUTUBE_GEMINI_BASE_URL",
    )
    lookback_days: int = Field(default=1, alias="YOUTUBE_LOOKBACK_DAYS")
    transcribe_batch_size: int = Field(default=50, alias="YOUTUBE_TRANSCRIBE_BATCH_SIZE")
    transcribe_candidate_pool_multiplier: int = Field(
        default=10, alias="YOUTUBE_TRANSCRIBE_CANDIDATE_POOL_MULTIPLIER"
    )
    daily_transcribe_limit: int = Field(default=100, alias="YOUTUBE_DAILY_TRANSCRIBE_LIMIT")
    transcribe_max_attempts: int = Field(default=3, alias="YOUTUBE_TRANSCRIBE_MAX_ATTEMPTS")

    model_config = SettingsConfigDict(
        # Use .env in the youtube_crypto package root
        env_file=str(Path(__file__).parent.parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @classmethod
    def from_env(cls) -> "YouTubeCryptoSettings":
        return cls()

    async def create_db_pool(self) -> aiomysql.Pool:
        """
        Create aiomysql connection pool for Doris (MySQL protocol).

        Returns:
            aiomysql.Pool instance
        """
        return await aiomysql.create_pool(
            host=self._db_host,
            port=self._db_port,
            user=self._db_user,
            password=self._db_password,
            db=self._db_name,
            minsize=self.db_min_pool_size,
            maxsize=self.db_max_pool_size,
            autocommit=True,
            charset="utf8mb4",
            connect_timeout=10,
        )

    @property
    def _db_host(self) -> str:
        return self._parsed_db_url["host"]

    @property
    def _db_port(self) -> int:
        return int(self._parsed_db_url.get("port", 3306))

    @property
    def _db_user(self) -> str:
        return self._parsed_db_url["user"]

    @property
    def _db_password(self) -> str:
        return self._parsed_db_url.get("password", "")

    @property
    def _db_name(self) -> str:
        return self._parsed_db_url.get("database", "")

    @property
    def _parsed_db_url(self) -> dict:
        """
        Parse a MySQL/Doris style URL: mysql://user:pass@host:port/db
        """
        from urllib.parse import urlparse

        parsed = urlparse(self.database_url)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 3306,
            "user": parsed.username or "",
            "password": parsed.password or "",
            "database": (parsed.path or "").lstrip("/"),
        }


# Hard-coded constants (not configurable via env)
# Default Gemini model. The actual model used at runtime comes from
# YouTubeCryptoSettings.gemini_model (env GEMINI_MODEL); this constant is kept as a
# reference/fallback default only.
GEMINI_MODEL_NAME = "gemini-2.5-flash-lite"

# Analysis batch size per job run
ANALYSIS_BATCH_SIZE = 100

# Transcription batch size per job run (video transcription is expensive; keep it capped)
TRANSCRIBE_BATCH_SIZE = 50

# Pull a larger cheap metadata pool, then value-score it before paying for video tokens.
TRANSCRIBE_CANDIDATE_POOL_MULTIPLIER = 10

# Lookback window (in days) when querying uploads playlist and retryable videos.
LOOKBACK_DAYS = 1

# Minimum duration (seconds) for a video to be considered
MIN_DURATION_SECONDS = 180

VIDEO_DOMAIN_CATEGORIES = {
    "politics",
    "world",
    "market",
    "sports",
    "economy",
    "business_tech",
    "other",
}

PROMPT_PATHS = {
    "crypto": "prompts/youtube_video_analysis_prompt.md",
    "politics": "prompts/politics_video_analysis_prompt.md",
    "world": "prompts/world_video_analysis_prompt.md",
    "market": "prompts/market_video_analysis_prompt.md",
    "sports": "prompts/sports_video_analysis_prompt.md",
    "economy": "prompts/economy_video_analysis_prompt.md",
    "business_tech": "prompts/business_tech_video_analysis_prompt.md",
    # "other" does not require a downstream analysis prompt because
    # videos routed to "other" are skipped from detailed analysis.
    "router": "prompts/video_domain_router_prompt.md",
}


def get_prompt_path(category: str = "crypto") -> Path:
    """Return the path to the prompt file for a given category."""
    prompt_key = category or "crypto"
    if prompt_key not in PROMPT_PATHS:
        prompt_key = "crypto"
    return Path(__file__).parent.parent / PROMPT_PATHS[prompt_key]
