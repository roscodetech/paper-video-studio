import json
from pathlib import Path

from paper_video_editor import VersionManager


def _sample_points():
    return [
        {"text": "Quote 1", "narration": "Narration 1"},
        {"text": "Quote 2", "narration": "Narration 2"},
    ]


def test_save_writes_working_copy_and_auto_snapshot(tmp_path):
    vm = VersionManager(work_dir=tmp_path)
    points = _sample_points()

    vm.save(points)

    working = tmp_path / "points.json"
    history = tmp_path / "points_history"

    assert working.exists()
    assert json.loads(working.read_text(encoding="utf-8")) == points
    assert history.exists()
    snapshots = list(history.glob("auto-*.json"))
    assert len(snapshots) == 1
    assert json.loads(snapshots[0].read_text(encoding="utf-8")) == points


def test_save_as_version_writes_named_only(tmp_path):
    vm = VersionManager(work_dir=tmp_path)
    points = _sample_points()
    vm.save(points)
    history = tmp_path / "points_history"
    before = set(history.glob("*.json"))

    vm.save_as_version(points, name="punchy v1")

    after = set(history.glob("*.json"))
    new_files = after - before
    assert len(new_files) == 1
    named_file = new_files.pop()
    assert named_file.name == "named-punchy-v1.json"
    assert json.loads(named_file.read_text(encoding="utf-8")) == points


def test_load_returns_named_version_contents(tmp_path):
    vm = VersionManager(work_dir=tmp_path)
    points = _sample_points()
    vm.save_as_version(points, name="alt")

    loaded = vm.load("named-alt.json")

    assert loaded == points


def test_list_versions_named_first_then_auto(tmp_path):
    vm = VersionManager(work_dir=tmp_path)
    vm.save(_sample_points())
    vm.save_as_version(_sample_points(), name="a")
    vm.save(_sample_points())

    versions = vm.list_versions()

    names = [v["filename"] for v in versions]
    named = [n for n in names if n.startswith("named-")]
    auto = [n for n in names if n.startswith("auto-")]
    assert names == named + auto
