from youtube_crypto.models import VideoAnalysis
from youtube_crypto.repositories.analysis_repository import INSERT_SQL, _insert_params


def _analysis() -> VideoAnalysis:
    return VideoAnalysis(
        video_id="v",
        analysis_version="youtube_crypto_v2",
        model_name="gemini-3-pro-preview",
        summary_brief="brief",
        key_tokens=["BTC"],
        key_narratives=["ETF"],
        claims=[{"claim_text": "BTC to 120k", "target": "$120k"}],
        events_referenced=["spot BTC ETF flows"],
        catalysts_mentioned=[{"event": "ETF decision"}],
        risks_mentioned=["regulation"],
    )


def test_analysis_insert_params_match_placeholder_count():
    assert INSERT_SQL.count("%s") == len(_insert_params(_analysis()))


def test_analysis_insert_serialises_claims_to_json():
    params = _insert_params(_analysis())
    claim_blobs = [p for p in params if isinstance(p, str) and "claim_text" in p]
    assert claim_blobs and '"target": "$120k"' in claim_blobs[0]
