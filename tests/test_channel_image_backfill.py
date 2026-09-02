import youtube_crypto.services.youtube_fetch_service as fetch_mod
from youtube_crypto.services.youtube_fetch_service import YouTubeFetchService


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_fetches_highest_available_channel_image_by_handle(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append(params)
        return _Response(
            {
                "items": [
                    {
                        "snippet": {
                            "thumbnails": {
                                "medium": {"url": "https://yt3.example/medium"},
                                "high": {"url": "https://yt3.example/high"},
                            }
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(fetch_mod.requests, "get", fake_get)
    service = YouTubeFetchService(api_key="test-key")

    assert service.get_channel_image_from_handle("@CoinBureau") == "https://yt3.example/high"
    assert calls[0]["forHandle"] == "CoinBureau"
