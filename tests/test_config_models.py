from youtube_crypto.config.config import GEMINI_MODEL_NAME, YouTubeCryptoSettings


def test_default_models_are_flash_lite(monkeypatch):
    monkeypatch.setenv("YOUTUBE_DATA_API_KEY", "yt")
    monkeypatch.setenv("YOUTUBE_GEMINI_API_KEY", "gemini")
    monkeypatch.setenv("DATABASE_URL", "mysql://u:p@localhost:9030/public_data")
    monkeypatch.delenv("YOUTUBE_GEMINI_MODEL", raising=False)
    monkeypatch.delenv("YOUTUBE_TRANSCRIBE_MODEL", raising=False)

    settings = YouTubeCryptoSettings.from_env()

    assert settings.gemini_model == "gemini-2.5-flash"
    assert settings.transcription_model == "gemini-2.5-flash-lite"
    assert settings.lookback_days == 1
    assert settings.transcribe_batch_size == 50
    assert settings.daily_transcribe_limit == 100
    assert settings.transcribe_max_attempts == 3
    assert GEMINI_MODEL_NAME == "gemini-2.5-flash"


def test_data_api_key_list_supports_comma_separated_fallbacks(monkeypatch):
    monkeypatch.setenv("YOUTUBE_DATA_API_KEY", "first, second")
    monkeypatch.setenv("YOUTUBE_GEMINI_API_KEY", "gemini")
    monkeypatch.setenv("DATABASE_URL", "mysql://u:p@localhost:9030/public_data")

    settings = YouTubeCryptoSettings(_env_file=None)

    assert settings.youtube_data_api_keys == ("first", "second")


def test_doris_component_configuration_is_supported(monkeypatch):
    monkeypatch.setenv("YOUTUBE_DATA_API_KEY", "yt")
    monkeypatch.setenv("YOUTUBE_GEMINI_API_KEY", "gemini")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DORIS_HOST", "doris.internal")
    monkeypatch.setenv("DORIS_PORT", "9030")
    monkeypatch.setenv("DORIS_USER", "writer")
    monkeypatch.setenv("DORIS_PASSWORD", "secret")
    monkeypatch.setenv("DORIS_DATABASE", "public_data")

    settings = YouTubeCryptoSettings(_env_file=None)

    assert settings._db_host == "doris.internal"
    assert settings._db_port == 9030
    assert settings._db_user == "writer"
    assert settings._db_password == "secret"
    assert settings._db_name == "public_data"
