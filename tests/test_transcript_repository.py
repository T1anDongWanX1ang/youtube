from youtube_crypto.models.transcript import VideoTranscript
from youtube_crypto.repositories.transcript_repository import INSERT_SQL, _insert_params


def test_insert_params_match_placeholder_count():
    sample = VideoTranscript(
        video_id="v1",
        full_text="hello world",
        segments=[{"start": 0, "text": "hello world"}],
        word_count=2,
        duration_covered_sec=0,
    )
    assert INSERT_SQL.count("%s") == len(_insert_params(sample))


def test_insert_params_serialises_segments_to_json():
    sample = VideoTranscript(video_id="v1", full_text="hi", segments=[{"start": 1, "text": "hi"}])
    params = _insert_params(sample)
    # segments_json is the 4th column
    assert params[3] == '[{"start": 1, "text": "hi"}]'
