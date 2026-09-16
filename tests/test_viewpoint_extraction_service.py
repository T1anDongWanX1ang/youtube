import json
from datetime import datetime, timezone
from types import SimpleNamespace

from youtube_crypto.services import viewpoint_extraction_service as module
from youtube_crypto.services.viewpoint_extraction_service import ViewpointExtractionService


def test_extract_supplies_source_time_and_preserves_temporal_grounding(monkeypatch):
    captured = {}

    def fake_generate_text(**kwargs):
        captured.update(kwargs)
        return (
            json.dumps(
                [
                    {
                        "title": "Later-cycle forecast uses the 2022 ATH as a reference",
                        "core_judgement": (
                            "The speaker uses the approximately $68K prior-cycle ATH "
                            "discussed in the 2022 context to forecast the later cycle."
                        ),
                        "subject": (
                            "The 2022 Bitcoin ATH comparison impacts the later-cycle forecast"
                        ),
                        "follow_up": "Watch the later-cycle price path.",
                    }
                ]
            ),
            {},
        )

    monkeypatch.setattr(module, "generate_text", fake_generate_text)
    settings = SimpleNamespace(
        youtube_gemini_api_key="key",
        gemini_model="model",
        gemini_base_url="https://example.test",
    )

    drafts = ViewpointExtractionService(settings=settings).extract(
        "The speaker reviews the approximately $68K ATH in the 2022 context, then uses "
        "that historical cycle to forecast the next move.",
        "4wY_8mHp85Y",
        source_published_at=datetime(2024, 3, 4, 5, 6, tzinfo=timezone.utc),
        video_title="Bitcoin cycle comparison",
    )

    prompt = captured["prompt"]
    assert "Source published at: 2024-03-04T05:06:00+00:00" in prompt
    assert "Video title: Bitcoin cycle comparison" in prompt
    assert "A historical ATH must never be described as the current" in prompt
    assert "Never turn \"X happened in 2022 and is used to predict Y\"" in prompt
    assert prompt.count("The speaker reviews the approximately $68K ATH") == 1
    assert drafts[0].title == "Later-cycle forecast uses the 2022 ATH as a reference"


def test_extract_remains_compatible_when_source_metadata_is_unavailable(monkeypatch):
    captured = {}

    def fake_generate_text(**kwargs):
        captured.update(kwargs)
        return "[]", {}

    monkeypatch.setattr(module, "generate_text", fake_generate_text)
    settings = SimpleNamespace(
        youtube_gemini_api_key="key",
        gemini_model="model",
        gemini_base_url="https://example.test",
    )

    assert ViewpointExtractionService(settings=settings).extract("A thesis", "video-1") == []
    assert "Source published at: Unknown" in captured["prompt"]
    assert "Video title: Unknown" in captured["prompt"]
