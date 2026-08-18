import json

import pytest

import youtube_crypto.utils.gemini_rest as g_mod


class _Resp:
    status_code = 200
    text = ""

    def __init__(self, chunks):
        self._chunks = chunks

    def iter_lines(self, decode_unicode=True):
        for chunk in self._chunks:
            yield "data: " + json.dumps(chunk)

    def json(self):
        return self._chunks[-1]


def test_generate_text_sends_json_schema(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout, stream=None):
        captured["body"] = json
        return _Resp([
            {"candidates": [{"content": {"parts": [{"text": "{}"}]}, "finishReason": "STOP"}]}
        ])

    monkeypatch.setattr(g_mod.requests, "post", fake_post)

    g_mod.generate_text(
        api_key="k",
        model="m",
        prompt="p",
        response_mime_type="application/json",
        response_schema={"type": "object", "properties": {"claims": {"type": "array"}}},
    )

    config = captured["body"]["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseSchema"]["properties"]["claims"]["type"] == "array"


def test_stream_request_fails_fast_when_output_is_truncated(monkeypatch):
    def fake_post(url, json, timeout, stream=None):
        return _Resp([
            {"candidates": [{"content": {"parts": [{"text": "{\\\"claims\\\": ["}]}, "finishReason": "MAX_TOKENS"}]}
        ])

    monkeypatch.setattr(g_mod.requests, "post", fake_post)

    with pytest.raises(RuntimeError, match="MAX_TOKENS"):
        g_mod.generate_text(api_key="k", model="m", prompt="p")


def test_video_stream_returns_partial_text_when_output_hits_token_limit(monkeypatch):
    def fake_post(url, json, timeout, stream):
        return _Resp([
            {
                "candidates": [
                    {"content": {"parts": [{"text": "[00:00] partial"}]}, "finishReason": "MAX_TOKENS"}
                ],
                "usageMetadata": {"totalTokenCount": 42},
            }
        ])

    monkeypatch.setattr(g_mod.requests, "post", fake_post)

    text, usage = g_mod.generate_from_video(
        api_key="k", model="m", video_url="https://youtube.test/v", prompt="p"
    )

    assert text == "[00:00] partial"
    assert usage == {"totalTokenCount": 42, "finishReason": "MAX_TOKENS"}
