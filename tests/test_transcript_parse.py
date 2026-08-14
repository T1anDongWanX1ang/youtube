from youtube_crypto.utils.transcript_parse import parse_segments


def test_parse_mm_ss_and_hh_mm_ss():
    raw = "[00:05] hello world\n[1:02:10] later part"
    segs = parse_segments(raw)
    assert segs[0] == {"start": 5, "text": "hello world"}
    assert segs[1]["start"] == 3730
    assert segs[1]["text"] == "later part"


def test_continuation_line_appends_to_previous_segment():
    segs = parse_segments("[00:01] first\ncontinued here")
    assert len(segs) == 1
    assert segs[0]["start"] == 1
    assert segs[0]["text"] == "first continued here"


def test_lines_before_first_timestamp_are_dropped():
    raw = "LANG: en\n\n[00:00] start here"
    segs = parse_segments(raw)
    assert len(segs) == 1
    assert segs[0]["start"] == 0
    assert segs[0]["text"] == "start here"


def test_empty_input_returns_empty_list():
    assert parse_segments("") == []
    assert parse_segments(None) == []
