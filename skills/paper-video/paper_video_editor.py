"""paper_video_editor.py — Tkinter editor for paper-video points + versioning helpers."""

from __future__ import annotations

import re
from typing import List, Dict, Any


_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]")


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
