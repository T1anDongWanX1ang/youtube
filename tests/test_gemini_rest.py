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


def test_generate_text_sends_json_schema(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout, stream):
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
    def fake_post(url, json, timeout, stream):
        return _Resp([
            {"candidates": [{"content": {"parts": [{"text": "{\\\"claims\\\": ["}]}, "finishReason": "MAX_TOKENS"}]}
        ])

    monkeypatch.setattr(g_mod.requests, "post", fake_post)

    with pytest.raises(RuntimeError, match="MAX_TOKENS"):
        g_mod.generate_text(api_key="k", model="m", prompt="p")
