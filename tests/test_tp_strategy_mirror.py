import asyncio
from datetime import datetime

from youtube_crypto.config.config import YouTubeCryptoSettings
from youtube_crypto.models import ResearchViewpoint
from youtube_crypto.repositories.tp_strategy_repository import TpStrategyRepository


def _set_required_settings(monkeypatch):
    monkeypatch.setenv("YOUTUBE_DATA_API_KEY", "yt")
    monkeypatch.setenv("YOUTUBE_GEMINI_API_KEY", "gemini")
    monkeypatch.setenv("DATABASE_URL", "mysql://source:pw@source-db:9030/source")


def test_trade_db_variables_enable_tp_strategy_mirror(monkeypatch):
    _set_required_settings(monkeypatch)
    monkeypatch.setenv("TRADE_DB_HOST", "strategy-db")
    monkeypatch.setenv("TRADE_DB_PORT", "3307")
    monkeypatch.setenv("TRADE_DB_USER", "writer")
    monkeypatch.setenv("TRADE_DB_PASSWORD", "secret")
    monkeypatch.setenv("TRADE_DB_NAME", "tp_strategy")

    settings = YouTubeCryptoSettings(_env_file=None)

    assert settings.tp_strategy_enabled is True
    assert settings._parsed_tp_strategy_db_url == {
        "host": "strategy-db",
        "port": 3307,
        "user": "writer",
        "password": "secret",
        "database": "tp_strategy",
    }


def test_partial_tp_strategy_configuration_is_not_enabled(monkeypatch):
    _set_required_settings(monkeypatch)
    for name in (
        "TRADE_DB_HOST",
        "TRADE_DB_PORT",
        "TRADE_DB_USER",
        "TRADE_DB_PASSWORD",
        "TRADE_DB_NAME",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TP_STRATEGY_HOST", "strategy-db")

    settings = YouTubeCryptoSettings(_env_file=None)

    assert settings.tp_strategy_enabled is False
    assert "missing" in (settings._tp_strategy_connection_error or "")


class _FakeCursor:
    def __init__(self):
        self.execute_calls = []
        self.executemany_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def execute(self, sql, params=None):
        self.execute_calls.append((sql, params))

    async def executemany(self, sql, params):
        self.executemany_calls.append((sql, params))

    async def fetchone(self):
        return None


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def cursor(self):
        return self._cursor


class _FakePool:
    def __init__(self):
        self.cursor = _FakeCursor()

    def acquire(self):
        return _FakeConnection(self.cursor)


def test_mirror_upserts_viewpoints_and_channels():
    pool = _FakePool()
    repository = TpStrategyRepository(pool)
    viewpoint = ResearchViewpoint(
        viewpoint_id="vp-1",
        source_id="video-1",
        source_url="https://www.youtube.com/watch?v=video-1",
        source_author_id="channel-1",
        source_author_handle="@channel",
        source_published_at=datetime(2026, 8, 26, 12, 0, 0),
        speaker_handle="@channel",
        title="A viewpoint",
        core_judgment="BTC will rise.",
        subject="BTC",
        follow_up="Watch liquidity.",
    )

    asyncio.run(repository.upsert_viewpoints([viewpoint]))
    asyncio.run(
        repository.sync_channels(
            [
                {
                    "channel_id": "channel-1",
                    "handle": "@channel",
                    "title": "Channel",
                    "is_active": True,
                }
            ]
        )
    )

    viewpoint_sql, viewpoint_params = pool.cursor.executemany_calls[0]
    assert "synced_at" in viewpoint_sql
    assert "ON DUPLICATE KEY UPDATE" in viewpoint_sql
    assert viewpoint_params[0][0] == "vp-1"

    assert "information_schema.tables" in pool.cursor.execute_calls[0][0]
    assert "CREATE TABLE IF NOT EXISTS youtube_crypto_channels" in pool.cursor.execute_calls[1][0]
    channel_sql, channel_params = pool.cursor.executemany_calls[1]
    assert "ON DUPLICATE KEY UPDATE" in channel_sql
    assert channel_params[0][4] == 1
