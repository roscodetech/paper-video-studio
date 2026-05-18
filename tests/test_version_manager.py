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


import os
import time
from datetime import datetime, timedelta


def test_prune_keeps_named_versions(tmp_path):
    vm = VersionManager(work_dir=tmp_path)
    vm.save_as_version(_sample_points(), name="keepme")
    history = tmp_path / "points_history"
    named = history / "named-keepme.json"
    old_time = (datetime.now() - timedelta(days=365)).timestamp()
    os.utime(named, (old_time, old_time))

    vm.prune(max_auto=50, max_age_days=30)

    assert named.exists()


def test_prune_removes_old_auto_snapshots(tmp_path):
    vm = VersionManager(work_dir=tmp_path)
    vm.save(_sample_points())
    history = tmp_path / "points_history"
    snapshot = next(history.glob("auto-*.json"))
    old_time = (datetime.now() - timedelta(days=60)).timestamp()
    os.utime(snapshot, (old_time, old_time))

    vm.prune(max_auto=50, max_age_days=30)

    assert not snapshot.exists()


def test_prune_caps_auto_to_max_count(tmp_path):
    vm = VersionManager(work_dir=tmp_path)
    for _ in range(5):
        vm.save(_sample_points())
        time.sleep(0.01)
    history = tmp_path / "points_history"
    assert len(list(history.glob("auto-*.json"))) == 5

    vm.prune(max_auto=2, max_age_days=30)

    remaining = sorted(history.glob("auto-*.json"))
    assert len(remaining) == 2
