"""paper_video_editor.py — Tkinter editor for paper-video points + versioning helpers."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any


_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", name.lower()).strip()
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug or "untitled"


class VersionManager:
    """Manage points.json working copy plus auto-snapshot and named version history."""

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.working_file = self.work_dir / "points.json"
        self.history_dir = self.work_dir / "points_history"

    def _ensure_history(self) -> None:
        self.history_dir.mkdir(parents=True, exist_ok=True)

    def _write_json(self, path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def save(self, points: list) -> Path:
        """Write working copy and an auto-snapshot. Returns the snapshot path."""
        self._ensure_history()
        self._write_json(self.working_file, points)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        snapshot = self.history_dir / f"auto-{ts}.json"
        suffix = 0
        while snapshot.exists():
            suffix += 1
            snapshot = self.history_dir / f"auto-{ts}-{suffix}.json"
        self._write_json(snapshot, points)
        return snapshot

    def save_as_version(self, points: list, name: str) -> Path:
        """Write a named version. Does not modify the working copy."""
        self._ensure_history()
        slug = _slugify(name)
        named = self.history_dir / f"named-{slug}.json"
        self._write_json(named, points)
        return named

    def load(self, filename: str) -> list:
        """Load a specific history file by filename."""
        path = self.history_dir / filename
        return json.loads(path.read_text(encoding="utf-8"))

    def list_versions(self) -> list:
        """Return list of versions, named first then auto (newest first)."""
        if not self.history_dir.exists():
            return []
        named = sorted(self.history_dir.glob("named-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        auto = sorted(self.history_dir.glob("auto-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [{"filename": p.name, "mtime": p.stat().st_mtime} for p in (named + auto)]


def naive_defaults(pages: List[Dict[str, Any]], max_points: int = 5) -> List[Dict[str, str]]:
    """Generate naive point defaults: longest distinctive sentence per page, capped at max_points."""
    candidates: List[Dict[str, Any]] = []
    for page in pages:
        text = page.get("text", "")
        sentences = [s.strip() for s in _SENTENCE_RE.findall(text)]
        sentences = [s for s in sentences if len(s.split()) >= 5]
        if not sentences:
            continue
        longest = max(sentences, key=len)
        candidates.append({"page": page.get("page", 0), "sentence": longest, "length": len(longest)})

    candidates.sort(key=lambda c: c["length"], reverse=True)
    selected = candidates[:max_points]

    return [
        {"text": c["sentence"], "narration": ""}
        for c in selected
    ]
