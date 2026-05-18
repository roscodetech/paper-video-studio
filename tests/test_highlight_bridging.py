from paper_video import _norm_token, _bridge_word_gaps


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
