"""paper_video_editor.py — Tkinter editor for paper-video points + versioning helpers."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any


_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]")


# GUI launcher defined at the bottom of this file once PaperVideoEditor is declared.


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

    def prune(self, max_auto: int = 50, max_age_days: int = 30) -> int:
        """Remove auto snapshots older than max_age_days OR beyond max_auto newest. Never touch named.

        Returns the number of files deleted."""
        if not self.history_dir.exists():
            return 0
        auto_files = sorted(
            self.history_dir.glob("auto-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        cutoff = datetime.now().timestamp() - max_age_days * 86400
        deleted = 0
        for idx, path in enumerate(auto_files):
            too_old = path.stat().st_mtime < cutoff
            too_many = idx >= max_auto
            if too_old or too_many:
                path.unlink()
                deleted += 1
        return deleted


# ---------- Tkinter editor ----------

import os
import queue as _queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog


class PaperVideoEditor:
    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.vm = VersionManager(self.work_dir)
        self.points: list = []
        self.selected_idx: int | None = None
        self.dirty = False
        self._suppress_dirty = False

        self._load_points_or_defaults()
        pages_file = self.work_dir / "pages.json"
        self.pages = json.loads(pages_file.read_text(encoding="utf-8")) if pages_file.exists() else []

        self.root = tk.Tk()
        self.root.title(f"Paper Video Editor — {self.work_dir.name}")
        self.root.geometry("1200x720")
        self._build_layout()
        self._refresh_point_list()

    def _load_points_or_defaults(self) -> None:
        working = self.work_dir / "points.json"
        if working.exists():
            self.points = json.loads(working.read_text(encoding="utf-8"))
            return
        pages_file = self.work_dir / "pages.json"
        if pages_file.exists():
            pages = json.loads(pages_file.read_text(encoding="utf-8"))
            self.points = naive_defaults(pages, max_points=5)
        else:
            self.points = []

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)

        # Left: points list + controls
        left = ttk.Frame(outer)
        left.pack(side="left", fill="y")

        ttk.Label(left, text="Points").pack(anchor="w")
        self.point_listbox = tk.Listbox(left, width=40, height=24, exportselection=False)
        self.point_listbox.pack(fill="y", expand=False)
        self.point_listbox.bind("<<ListboxSelect>>", self._on_point_select)

        btn_row = ttk.Frame(left)
        btn_row.pack(fill="x", pady=4)
        ttk.Button(btn_row, text="+ Add", command=self._add_point).pack(side="left")
        ttk.Button(btn_row, text="↑", command=lambda: self._move_point(-1)).pack(side="left")
        ttk.Button(btn_row, text="↓", command=lambda: self._move_point(1)).pack(side="left")
        ttk.Button(btn_row, text="🗑", command=self._remove_point).pack(side="left")

        # Right: page selector + selectable text + (edit panes in Task 9)
        self.right = ttk.Frame(outer)
        self.right.pack(side="right", fill="both", expand=True, padx=(8, 0))

        top = ttk.Frame(self.right)
        top.pack(fill="x")
        ttk.Label(top, text="Page:").pack(side="left")
        self.page_var = tk.StringVar()
        self.page_selector = ttk.Combobox(top, textvariable=self.page_var, state="readonly", width=10)
        self.page_selector.pack(side="left", padx=4)
        self.page_selector.bind("<<ComboboxSelected>>", self._on_page_change)

        self.page_text = tk.Text(self.right, height=14, wrap="word")
        self.page_text.pack(fill="both", expand=True, pady=4)
        self.page_text.configure(state="disabled")

        ttk.Button(self.right, text="⬆ Use selection as quote", command=self._use_selection_as_quote).pack(anchor="w")

        # Edit panes
        self.edit_frame = ttk.Frame(self.right)
        self.edit_frame.pack(fill="both", expand=False, pady=8)

        ttk.Label(self.edit_frame, text="Quote (editable):").pack(anchor="w")
        self.quote_text = tk.Text(self.edit_frame, height=3, wrap="word")
        self.quote_text.pack(fill="x")
        self.quote_text.bind("<<Modified>>", self._on_quote_modified)

        ttk.Label(self.edit_frame, text="Narration (editable):").pack(anchor="w", pady=(6, 0))
        self.narration_text = tk.Text(self.edit_frame, height=5, wrap="word")
        self.narration_text.pack(fill="x")
        self.narration_text.bind("<<Modified>>", self._on_narration_modified)

    def _refresh_point_list(self) -> None:
        self.point_listbox.delete(0, tk.END)
        for i, p in enumerate(self.points):
            label = f"{i+1}. {p.get('text', '')[:50]}"
            self.point_listbox.insert(tk.END, label)
        if self.selected_idx is not None and 0 <= self.selected_idx < len(self.points):
            self.point_listbox.selection_set(self.selected_idx)

    def _on_point_select(self, _event) -> None:
        self._sync_edit_panes_to_model()
        sel = self.point_listbox.curselection()
        self.selected_idx = sel[0] if sel else None
        self._refresh_edit_panes()

    def _add_point(self) -> None:
        self.points.append({"text": "", "narration": ""})
        self.selected_idx = len(self.points) - 1
        self.dirty = True
        self._refresh_point_list()

    def _remove_point(self) -> None:
        if self.selected_idx is None:
            return
        del self.points[self.selected_idx]
        self.selected_idx = None
        self.dirty = True
        self._refresh_point_list()

    def _move_point(self, delta: int) -> None:
        if self.selected_idx is None:
            return
        new_idx = self.selected_idx + delta
        if not (0 <= new_idx < len(self.points)):
            return
        self.points[self.selected_idx], self.points[new_idx] = (
            self.points[new_idx],
            self.points[self.selected_idx],
        )
        self.selected_idx = new_idx
        self.dirty = True
        self._refresh_point_list()

    def _populate_page_selector(self) -> None:
        labels = [f"Page {p.get('page', i) + 1}" for i, p in enumerate(self.pages)]
        self.page_selector["values"] = labels
        if labels:
            self.page_selector.current(0)
            self._on_page_change(None)

    def _on_page_change(self, _event) -> None:
        idx = self.page_selector.current()
        if idx < 0 or idx >= len(self.pages):
            return
        text = self.pages[idx].get("text", "")
        self.page_text.configure(state="normal")
        self.page_text.delete("1.0", tk.END)
        self.page_text.insert("1.0", text)
        self.page_text.configure(state="disabled")

    def _use_selection_as_quote(self) -> None:
        if self.selected_idx is None:
            messagebox.showinfo("No point selected", "Select a point in the list first.")
            return
        try:
            self.page_text.configure(state="normal")
            selected = self.page_text.selection_get()
        except tk.TclError:
            messagebox.showinfo("No selection", "Highlight some text in the page first.")
            return
        finally:
            self.page_text.configure(state="disabled")

        selected = " ".join(selected.split())
        self.points[self.selected_idx]["text"] = selected
        self.dirty = True
        self._refresh_point_list()
        self._refresh_edit_panes()

    def _refresh_edit_panes(self) -> None:
        self._suppress_dirty = True
        self.quote_text.delete("1.0", tk.END)
        self.narration_text.delete("1.0", tk.END)
        if self.selected_idx is not None and 0 <= self.selected_idx < len(self.points):
            p = self.points[self.selected_idx]
            self.quote_text.insert("1.0", p.get("text", ""))
            self.narration_text.insert("1.0", p.get("narration", ""))
        self.quote_text.edit_modified(False)
        self.narration_text.edit_modified(False)
        self._suppress_dirty = False

    def _on_quote_modified(self, _event) -> None:
        if self._suppress_dirty:
            self.quote_text.edit_modified(False)
            return
        if self.selected_idx is None:
            return
        new_value = self.quote_text.get("1.0", "end-1c")
        self.points[self.selected_idx]["text"] = new_value
        self.dirty = True
        self.quote_text.edit_modified(False)
        self.point_listbox.delete(self.selected_idx)
        self.point_listbox.insert(self.selected_idx, f"{self.selected_idx+1}. {new_value[:50]}")
        self.point_listbox.selection_set(self.selected_idx)

    def _on_narration_modified(self, _event) -> None:
        if self._suppress_dirty:
            self.narration_text.edit_modified(False)
            return
        if self.selected_idx is None:
            return
        new_value = self.narration_text.get("1.0", "end-1c")
        self.points[self.selected_idx]["narration"] = new_value
        self.dirty = True
        self.narration_text.edit_modified(False)

    def _sync_edit_panes_to_model(self) -> None:
        if self.selected_idx is None:
            return
        if 0 <= self.selected_idx < len(self.points):
            self.points[self.selected_idx]["text"] = self.quote_text.get("1.0", "end-1c")
            self.points[self.selected_idx]["narration"] = self.narration_text.get("1.0", "end-1c")

    def run(self) -> None:
        self._populate_page_selector()
        self.root.mainloop()


def launch_editor(work_dir) -> None:
    work_dir = Path(work_dir)
    if not work_dir.exists():
        raise SystemExit(f"Work dir does not exist: {work_dir}")
    editor = PaperVideoEditor(work_dir)
    editor.run()


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
