"""Gemini REST client (streaming).

The official google-genai SDK crashes on some API keys (its error-response parser
raises `'str' object has no attribute 'get'`, masking the real HTTP status), so the
analysis and router services call Gemini through this thin REST wrapper instead.

Uses the streaming endpoint (streamGenerateContent?alt=sse) so long responses do not
hit a single-shot read timeout, and retries transient 429/500/503 with linear backoff.

The base URL is overridable via the YOUTUBE_GEMINI_BASE_URL env var (or an explicit
base_url argument), so the same code can target Google directly or a Gemini-native proxy
(e.g. https://api.rcouyi.com) for local testing with a third-party key.
"""
import json
import logging
import os
import time
from typing import Any, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

_RETRYABLE = (429, 500, 503)
_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"


def _endpoint(model: str, key: str, base_url: Optional[str] = None) -> str:
    base = (base_url or os.getenv("YOUTUBE_GEMINI_BASE_URL") or _DEFAULT_BASE_URL).rstrip("/")
    return f"{base}/v1beta/models/{model}:streamGenerateContent?alt=sse&key={key}"


def _generate_endpoint(model: str, key: str, base_url: Optional[str] = None) -> str:
    base = (base_url or os.getenv("YOUTUBE_GEMINI_BASE_URL") or _DEFAULT_BASE_URL).rstrip("/")
    return f"{base}/v1beta/models/{model}:generateContent?key={key}"


def _stream_request(
    url: str,
    body: dict,
    max_retries: int,
    timeout: tuple,
    *,
    allow_max_tokens: bool = False,
) -> Tuple[str, Optional[dict]]:
    """POST a streaming request and accumulate (full_text, usage_metadata)."""
    for attempt in range(max_retries):
        resp = requests.post(url, json=body, timeout=timeout, stream=True)
        if resp.status_code in _RETRYABLE:
            wait = 20 * (attempt + 1)
            logger.warning(
                "Gemini %s (retryable), waiting %ss (attempt %d/%d)",
                resp.status_code, wait, attempt + 1, max_retries,
            )
            if attempt + 1 < max_retries:
                time.sleep(wait)
            continue
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")

        text_parts: list[str] = []
        usage: Optional[dict] = None
        finish_reasons: list[str] = []
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            try:
                chunk: Any = json.loads(payload)
            except ValueError:
                continue
            for cand in chunk.get("candidates", []):
                finish_reason = cand.get("finishReason")
                if finish_reason:
                    finish_reasons.append(str(finish_reason))
                for part in cand.get("content", {}).get("parts", []):
                    if "text" in part:
                        text_parts.append(part["text"])
            if chunk.get("usageMetadata"):
                usage = chunk["usageMetadata"]
        if "MAX_TOKENS" in finish_reasons:
            if allow_max_tokens:
                # A transcript can continue from its final timestamp, so preserve the
                # streamed text instead of discarding it as an exception.
                usage = dict(usage or {})
                usage["finishReason"] = "MAX_TOKENS"
                return "".join(text_parts), usage
            total = usage.get("totalTokenCount") if usage else None
            raise RuntimeError(f"Gemini output truncated: finishReason=MAX_TOKENS total_tokens={total}")
        if not finish_reasons:
            wait = 20 * (attempt + 1)
            message = "Gemini stream ended without finishReason; treating response as incomplete"
            if attempt + 1 < max_retries:
                logger.warning("%s, waiting %ss (attempt %d/%d)", message, wait, attempt + 1, max_retries)
                time.sleep(wait)
                continue
            raise RuntimeError(message)
        bad_finish = [reason for reason in finish_reasons if reason != "STOP"]
        if bad_finish:
            raise RuntimeError(f"Gemini finished without STOP: finishReason={bad_finish[-1]}")
        return "".join(text_parts), usage

    raise RuntimeError(f"Gemini exhausted {max_retries} retries (last status was retryable or incomplete)")


def _generate_request(url: str, body: dict, max_retries: int, timeout: tuple) -> Tuple[str, Optional[dict]]:
    """POST a non-streaming request and return (full_text, usage_metadata)."""
    for attempt in range(max_retries):
        resp = requests.post(url, json=body, timeout=timeout)
        if resp.status_code in _RETRYABLE:
            wait = 20 * (attempt + 1)
            logger.warning(
                "Gemini %s (retryable), waiting %ss (attempt %d/%d)",
                resp.status_code, wait, attempt + 1, max_retries,
            )
            if attempt + 1 < max_retries:
                time.sleep(wait)
            continue
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")

        try:
            payload: Any = resp.json()
        except ValueError as exc:
            raise RuntimeError(f"Gemini returned non-JSON response: {resp.text[:300]}") from exc

        text_parts: list[str] = []
        finish_reasons: list[str] = []
        for cand in payload.get("candidates", []):
            finish_reason = cand.get("finishReason")
            if finish_reason:
                finish_reasons.append(str(finish_reason))
            for part in cand.get("content", {}).get("parts", []):
                if "text" in part:
                    text_parts.append(part["text"])

        usage = payload.get("usageMetadata")
        if "MAX_TOKENS" in finish_reasons:
            total = usage.get("totalTokenCount") if usage else None
            raise RuntimeError(f"Gemini output truncated: finishReason=MAX_TOKENS total_tokens={total}")
        if not finish_reasons:
            raise RuntimeError("Gemini response missing finishReason; treating response as incomplete")
        bad_finish = [reason for reason in finish_reasons if reason != "STOP"]
        if bad_finish:
            raise RuntimeError(f"Gemini finished without STOP: finishReason={bad_finish[-1]}")
        return "".join(text_parts), usage

    raise RuntimeError(f"Gemini exhausted {max_retries} retries (last status was retryable)")


def generate_from_video(
    api_key: str,
    model: str,
    video_url: str,
    prompt: str,
    *,
    max_output_tokens: int = 16384,
    temperature: float = 0.2,
    max_retries: int = 5,
    connect_timeout: float = 30.0,
    read_timeout: float = 600.0,
    base_url: Optional[str] = None,
) -> Tuple[str, Optional[dict]]:
    """Send a YouTube video URL + prompt to Gemini and stream back (full_text, usage)."""
    url = _endpoint(model, api_key, base_url)
    body = {
        "contents": [
            {
                "parts": [
                    {"file_data": {"file_uri": video_url}},
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": max_output_tokens,
            "temperature": temperature,
        },
    }
    return _stream_request(
        url,
        body,
        max_retries,
        (connect_timeout, read_timeout),
        allow_max_tokens=True,
    )


def generate_text(
    api_key: str,
    model: str,
    prompt: str,
    *,
    max_output_tokens: int = 16384,
    temperature: float = 0.2,
    max_retries: int = 5,
    connect_timeout: float = 30.0,
    read_timeout: float = 600.0,
    base_url: Optional[str] = None,
    response_mime_type: Optional[str] = None,
    response_schema: Optional[dict] = None,
) -> Tuple[str, Optional[dict]]:
    """Send a text-only prompt to Gemini and stream back (full_text, usage).

    Used by the analysis stage, which reads the stored transcript text instead of
    re-watching the video.
    """
    url = _generate_endpoint(model, api_key, base_url)
    generation_config: dict[str, Any] = {
        "maxOutputTokens": max_output_tokens,
        "temperature": temperature,
        "thinkingConfig": {"thinkingBudget": 0},
    }
    if response_mime_type:
        generation_config["responseMimeType"] = response_mime_type
    if response_schema:
        generation_config["responseSchema"] = response_schema
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }
    return _generate_request(url, body, max_retries, (connect_timeout, read_timeout))
