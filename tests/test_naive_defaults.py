import json
from pathlib import Path

from paper_video_editor import naive_defaults


def test_naive_defaults_returns_five_points_when_enough_sentences(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "sample_pages.json"
    pages = json.loads(fixture.read_text(encoding="utf-8"))

    points = naive_defaults(pages, max_points=5)

    assert len(points) == 5
    assert all("text" in p and "narration" in p for p in points)
    assert all(p["text"].strip() for p in points)


def test_naive_defaults_skips_very_short_sentences():
    pages = [{"page": 0, "text": "Hi. This is a long enough sentence to be selected as a point."}]
    points = naive_defaults(pages, max_points=5)
    for p in points:
        assert len(p["text"].split()) >= 5


def test_naive_defaults_caps_at_max_points():
    pages = [{"page": i, "text": f"This is sentence number {i} which is long enough to qualify for selection."} for i in range(10)]
    points = naive_defaults(pages, max_points=3)
    assert len(points) == 3
