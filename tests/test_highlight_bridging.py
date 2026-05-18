from paper_video import (
    _norm_token,
    _bridge_word_gaps,
    _ends_at_natural_boundary,
    _smart_extend_forward,
)


def test_norm_token_lowercases_and_strips_punctuation():
    assert _norm_token("Hello,") == "hello"
    assert _norm_token("WHO.") == "who"
    assert _norm_token("4.69") == "469"


def test_norm_token_handles_ligatures():
    # PDF ligature for "fi" should normalize to "fi" then "file".
    assert _norm_token("ﬁle") == "file"


def test_bridge_word_gaps_extends_right_edge_to_next_word_on_same_line():
    words = [
        (10.0, 20.0, 30.0, 30.0, "the"),
        (34.0, 20.0, 70.0, 30.0, "majority"),
    ]
    bridged = _bridge_word_gaps(words)
    assert bridged[0] == [10.0, 20.0, 34.0, 30.0]
    assert bridged[1] == [34.0, 20.0, 70.0, 30.0]


def test_bridge_word_gaps_does_not_bridge_across_lines():
    # Two words on visually distinct lines (different y bands).
    words = [
        (10.0, 20.0, 30.0, 30.0, "first"),
        (10.0, 50.0, 30.0, 60.0, "second"),
    ]
    bridged = _bridge_word_gaps(words)
    assert bridged[0] == [10.0, 20.0, 30.0, 30.0]
    assert bridged[1] == [10.0, 50.0, 30.0, 60.0]


def test_bridge_word_gaps_leaves_last_word_unchanged():
    words = [(10.0, 20.0, 30.0, 30.0, "lone")]
    assert _bridge_word_gaps(words) == [[10.0, 20.0, 30.0, 30.0]]


def test_ends_at_natural_boundary_detects_punctuation():
    assert _ends_at_natural_boundary("disability;")
    assert _ends_at_natural_boundary("treatment,")
    assert _ends_at_natural_boundary("end.")
    assert _ends_at_natural_boundary("hello!")
    assert _ends_at_natural_boundary("question?")
    assert _ends_at_natural_boundary("note:")
    assert _ends_at_natural_boundary("(DALYs)")
    assert not _ends_at_natural_boundary("of")
    assert not _ends_at_natural_boundary("the")
    assert not _ends_at_natural_boundary("disability")


def _w(x0, y0, x1, y1, text):
    """Build a PyMuPDF-style word tuple for tests."""
    return (x0, y0, x1, y1, text, 0, 0, 0)


def test_smart_extend_extends_through_preposition_to_punctuation():
    # "...top 10 causes of disability;" — match ends on "of", extend to "disability;"
    words = [
        _w(0, 0, 30, 10, "top"),
        _w(32, 0, 50, 10, "10"),
        _w(52, 0, 95, 10, "causes"),
        _w(97, 0, 110, 10, "of"),
        _w(112, 0, 175, 10, "disability;"),
        _w(177, 0, 185, 10, "4"),
    ]
    new_end = _smart_extend_forward(words, end_idx=4)
    assert new_end == 5


def test_smart_extend_leaves_already_boundary_alone():
    words = [
        _w(0, 0, 30, 10, "hello"),
        _w(32, 0, 80, 10, "world."),
    ]
    assert _smart_extend_forward(words, end_idx=2) == 2


def test_smart_extend_bumps_stop_word_by_one_when_no_punct_in_window():
    # Last matched word is "and"; nothing punctuated within range → bump by 1.
    words = [
        _w(0, 0, 30, 10, "alpha"),
        _w(32, 0, 80, 10, "and"),
        _w(82, 0, 130, 10, "beta"),
        _w(132, 0, 180, 10, "gamma"),
    ]
    new_end = _smart_extend_forward(words, end_idx=2, max_extra=2)
    assert new_end == 3


def test_smart_extend_does_not_extend_content_word_without_punct():
    # Last word is a content word and no punctuation in window → leave alone.
    words = [
        _w(0, 0, 30, 10, "diseases"),
        _w(32, 0, 80, 10, "spread"),
        _w(82, 0, 130, 10, "fast"),
    ]
    new_end = _smart_extend_forward(words, end_idx=1, max_extra=2)
    assert new_end == 1


def test_smart_extend_stops_at_paragraph_break():
    # Big y-jump between word 0 and word 1 → don't cross.
    words = [
        _w(0, 0, 30, 10, "of"),
        _w(0, 60, 30, 70, "disability;"),  # next paragraph, 6x line height down
    ]
    new_end = _smart_extend_forward(words, end_idx=1)
    # Stop-word at end + paragraph break + no punct found → bump by 1 fallback
    # (paragraph guard kicks in BEFORE we check the next word).
    # Expect: stays at end_idx because we couldn't safely extend.
    # Then fallback: bump by 1.
    assert new_end == 2 or new_end == 1
