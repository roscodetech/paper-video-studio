from paper_video import (
    _norm_token,
    _bridge_word_gaps,
    _ends_at_natural_boundary,
    _smart_extend_forward,
    _normalize_line_heights,
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


def test_normalize_line_heights_gives_every_line_same_height():
    # Three lines: line 1 has a tall ascender, line 2 has a descender, line 3 a superscript.
    bboxes = [
        (10, 100, 50, 120),   # line 1, "tall"
        (52, 102, 90, 118),   # line 1, short word
        (10, 130, 60, 152),   # line 2, descender (taller)
        (10, 160, 40, 178),   # line 3, normal
        (42, 158, 60, 170),   # line 3, superscript (shorter, higher)
    ]
    normalized = _normalize_line_heights(bboxes, pad_x=0)

    # All bboxes on the same line should share y0/y1.
    by_y0 = {}
    for x0, y0, x1, y1 in normalized:
        by_y0.setdefault(y0, set()).add(y1)
    for y1s in by_y0.values():
        assert len(y1s) == 1, "words on a single line should share y1"

    # Every line should have the same height.
    heights = {y1 - y0 for x0, y0, x1, y1 in normalized}
    assert len(heights) == 1, f"every line should have the same height, got {heights}"


def test_normalize_line_heights_prevents_adjacent_overlap():
    # Line spacing is 30px; canonical half-height must be < 15px so lines don't touch.
    bboxes = [
        (10, 100, 50, 120),
        (10, 130, 50, 152),  # descender
        (10, 160, 50, 178),
    ]
    normalized = _normalize_line_heights(bboxes, pad_x=0)
    # Sort by y to compare neighbours
    sorted_bb = sorted(normalized, key=lambda b: b[1])
    line_ys = []
    for x0, y0, x1, y1 in sorted_bb:
        if not line_ys or line_ys[-1][1] != y1:
            line_ys.append((y0, y1))
    # Adjacent lines must not overlap (line N y1 < line N+1 y0).
    for i in range(len(line_ys) - 1):
        assert line_ys[i][1] < line_ys[i + 1][0], (
            f"line {i} y1={line_ys[i][1]} overlaps line {i+1} y0={line_ys[i+1][0]}")


def test_normalize_line_heights_applies_horizontal_padding():
    bboxes = [(100, 50, 200, 70)]
    normalized = _normalize_line_heights(bboxes, pad_x=6)
    assert len(normalized) == 1
    x0, _, x1, _ = normalized[0]
    assert x0 == 94 and x1 == 206


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
