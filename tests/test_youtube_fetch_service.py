import youtube_crypto.services.youtube_fetch_service as fetch_mod
from youtube_crypto.services.youtube_fetch_service import YouTubeFetchService


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_switches_to_next_key_for_an_invalid_key(monkeypatch):
    responses = iter(
        [
            _Response(400, {"error": {"message": "API key not valid"}}),
            _Response(200, {"items": []}),
        ]
    )
    calls = []

    def fake_get(url, params, timeout):
        calls.append(params["key"])
        return next(responses)

    monkeypatch.setattr(fetch_mod.requests, "get", fake_get)
    service = YouTubeFetchService(api_key="first", fallback_api_keys=("second", "third"))

    response = service._get("/channels", {"part": "id"}, timeout=10)

    assert response.status_code == 200
    assert calls == ["first", "second"]


def test_keeps_current_key_for_a_non_key_error(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append(params["key"])
        return _Response(404, {"error": {"message": "not found"}})

    monkeypatch.setattr(fetch_mod.requests, "get", fake_get)
    service = YouTubeFetchService(api_key="first", fallback_api_keys=("second",))

    response = service._get("/videos", {"part": "snippet"}, timeout=10)

    assert response.status_code == 404
    assert calls == ["first"]
