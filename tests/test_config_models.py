from youtube_crypto.config.config import GEMINI_MODEL_NAME, YouTubeCryptoSettings


def test_default_models_are_flash_lite(monkeypatch):
    monkeypatch.setenv("YOUTUBE_DATA_API_KEY", "yt")
    monkeypatch.setenv("YOUTUBE_GEMINI_API_KEY", "gemini")
    monkeypatch.setenv("DATABASE_URL", "mysql://u:p@localhost:9030/public_data")
    monkeypatch.delenv("YOUTUBE_GEMINI_MODEL", raising=False)
    monkeypatch.delenv("YOUTUBE_TRANSCRIBE_MODEL", raising=False)

    settings = YouTubeCryptoSettings.from_env()

    assert settings.gemini_model == "gemini-2.5-flash-lite"
    assert settings.transcription_model == "gemini-2.5-flash-lite"
    assert settings.lookback_days == 1
    assert settings.transcribe_batch_size == 50
    assert settings.daily_transcribe_limit == 50
    assert GEMINI_MODEL_NAME == "gemini-2.5-flash-lite"
