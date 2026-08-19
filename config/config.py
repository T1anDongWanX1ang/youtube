import base64
import binascii
import os
from functools import cached_property
from pathlib import Path
from typing import Any, Optional
import re

import aiomysql
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class YouTubeCryptoSettings(BaseSettings):
    """
    Configuration for the YouTube Crypto agent.

    Configuration loaded from environment variables.
    """

    youtube_data_api_key: str = Field(..., alias="YOUTUBE_DATA_API_KEY")
    # Legacy fallback only. Production Gemini credentials are retrieved from
    # Secret Manager, so this value need not (and should not) be in .env.
    youtube_gemini_api_key: Optional[str] = Field(default=None, alias="YOUTUBE_GEMINI_API_KEY")
    gemini_secret_resource: Optional[str] = Field(
        default="projects/26425377297/secrets/predx-key/versions/2",
        alias="YOUTUBE_GEMINI_SECRET_RESOURCE",
    )
    gemini_secret_credentials_path: Optional[Path] = Field(
        default=None,
        alias="YOUTUBE_GEMINI_SECRET_CREDENTIALS_PATH",
    )

    # Database configuration
    # `DATABASE_URL` is retained for existing deployments.  Newer deployments
    # provide the Doris connection as individual values, which avoids URL
    # escaping issues in passwords.
    database_url: Optional[str] = Field(default=None, alias="DATABASE_URL")
    doris_host: Optional[str] = Field(default=None, alias="DORIS_HOST")
    doris_port: Optional[int] = Field(default=None, alias="DORIS_PORT")
    doris_user: Optional[str] = Field(default=None, alias="DORIS_USER")
    doris_password: Optional[str] = Field(default=None, alias="DORIS_PASSWORD")
    doris_database: Optional[str] = Field(default=None, alias="DORIS_DATABASE")
    db_min_pool_size: int = Field(default=2, alias="DB_MIN_POOL_SIZE")
    db_max_pool_size: int = Field(default=10, alias="DB_MAX_POOL_SIZE")

    # Claim extraction requires reliable structured JSON. Flash has proven stable
    # for this workload; transcription remains on Flash-Lite below.
    gemini_model: str = Field(default="gemini-2.5-flash", alias="YOUTUBE_GEMINI_MODEL")

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

    @property
    def youtube_data_api_keys(self) -> tuple[str, ...]:
        """Return one or more Data API keys configured as a comma-separated list."""
        keys = tuple(
            key for key in re.split(r"[,;\s]+", self.youtube_data_api_key.strip()) if key
        )
        if not keys:
            raise ValueError("YOUTUBE_DATA_API_KEY must contain at least one API key")
        return keys

    @property
    def _gemini_secret_credentials_file(self) -> Path:
        """Return the service-account file used only to read Secret Manager."""
        if self.gemini_secret_credentials_path:
            return self.gemini_secret_credentials_path

        application_credentials = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if application_credentials:
            return Path(application_credentials)

        return Path(__file__).parent.parent / "predx-secret-manager.json"

    @cached_property
    def resolved_youtube_gemini_api_key(self) -> str:
        """Fetch and cache the Gemini API key without persisting it locally."""
        if not self.gemini_secret_resource:
            if self.youtube_gemini_api_key:
                return self.youtube_gemini_api_key
            raise RuntimeError(
                "Set YOUTUBE_GEMINI_SECRET_RESOURCE or provide the legacy "
                "YOUTUBE_GEMINI_API_KEY"
            )

        credentials_file = self._gemini_secret_credentials_file
        if not credentials_file.is_file():
            raise RuntimeError(
                "Gemini Secret Manager credentials file is missing. Set "
                "YOUTUBE_GEMINI_SECRET_CREDENTIALS_PATH or "
                "GOOGLE_APPLICATION_CREDENTIALS."
            )

        credentials = service_account.Credentials.from_service_account_file(
            str(credentials_file),
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        session = AuthorizedSession(credentials)
        response = session.get(
            f"https://secretmanager.googleapis.com/v1/{self.gemini_secret_resource}:access",
            timeout=20,
        )
        if response.status_code != 200:
            raise RuntimeError(
                "Unable to access the Gemini API key from Secret Manager "
                f"(HTTP {response.status_code})."
            )

        try:
            encoded = response.json()["payload"]["data"]
            secret = base64.b64decode(encoded, validate=True).decode("utf-8").strip()
        except (KeyError, TypeError, ValueError, binascii.Error, UnicodeDecodeError) as exc:
            raise RuntimeError("Secret Manager returned an invalid Gemini API key payload.") from exc

        if not secret:
            raise RuntimeError("Secret Manager returned an empty Gemini API key.")
        return secret

    @model_validator(mode="after")
    def validate_database_connection(self) -> "YouTubeCryptoSettings":
        """Accept either the legacy URL or a complete Doris field set."""
        if self.database_url:
            return self

        required_values = {
            "DORIS_HOST": self.doris_host,
            "DORIS_PORT": self.doris_port,
            "DORIS_USER": self.doris_user,
            "DORIS_PASSWORD": self.doris_password,
            "DORIS_DATABASE": self.doris_database,
        }
        missing = [name for name, value in required_values.items() if value is None or value == ""]
        if missing:
            missing_values = ", ".join(missing)
            raise ValueError(
                "Set DATABASE_URL or all Doris connection variables; missing: "
                f"{missing_values}"
            )
        return self

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
            # A polling iteration can spend many minutes waiting for Gemini.  Doris
            # may close a MySQL-protocol connection while it is idle; recycle it
            # before the next write instead of reusing a stale pooled connection.
            pool_recycle=300,
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
        Return the configured Doris connection parameters.

        `DATABASE_URL` takes precedence when present. Otherwise use the
        discrete DORIS_* variables.
        """
        if not self.database_url:
            return {
                "host": self.doris_host or "localhost",
                "port": self.doris_port or 3306,
                "user": self.doris_user or "",
                "password": self.doris_password or "",
                "database": self.doris_database or "",
            }

        from urllib.parse import urlparse

        parsed = urlparse(self.database_url)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 3306,
            "user": parsed.username or "",
            "password": parsed.password or "",
            "database": (parsed.path or "").lstrip("/"),
        }


def resolve_gemini_api_key(settings: Any) -> str:
    """Resolve Secret Manager credentials while remaining compatible with test fakes."""
    return getattr(settings, "resolved_youtube_gemini_api_key", settings.youtube_gemini_api_key)


# Hard-coded constants (not configurable via env)
# Default Gemini model. The actual model used at runtime comes from
# YouTubeCryptoSettings.gemini_model (env GEMINI_MODEL); this constant is kept as a
# reference/fallback default only.
GEMINI_MODEL_NAME = "gemini-2.5-flash"

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
