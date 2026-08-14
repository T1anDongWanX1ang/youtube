from youtube_crypto.utils.transcript_coverage import compute_coverage


def test_coverage_ok_when_last_segment_near_duration():
    segs = [{"start": 0, "text": "a b c"}, {"start": 1700, "text": "d e"}]
    cov = compute_coverage(segs, duration_seconds=1800, min_ratio=0.9)
    assert cov["duration_covered_sec"] == 1700
    assert cov["word_count"] == 5
    assert cov["ok"] is True


def test_coverage_fails_when_truncated():
    cov = compute_coverage([{"start": 0, "text": "only intro"}], 1800, 0.9)
    assert cov["ok"] is False


def test_unknown_duration_ok_when_has_text():
    assert compute_coverage([{"start": 0, "text": "hi there"}], 0)["ok"] is True


def test_empty_segments_not_ok():
    assert compute_coverage([], 1800)["ok"] is False
