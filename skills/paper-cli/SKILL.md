---
name: paper-cli
description: Direct CLI access to the paper-video toolchain — fetch, render, and edit subcommands. Use ONLY for manual / partial operations on an existing work directory (re-render after editing points.json by hand, fetch text without running the agent pipeline, launch the Tkinter editor on a saved job, debug a specific render failure). For the default "turn a paper into a video" use case, use the `/paper-video-studio:paper-video` slash command which runs the full 5-agent pipeline. Triggers on phrases like "re-render this work dir", "open the editor on this output", "just fetch the paper text", "render with a different voice".
---

# paper-cli — manual access to the paper-video CLI

The full pipeline lives at the `/paper-video-studio:paper-video` slash command (curator → hook → script → truth-check → flow → render). This skill is the escape hatch for when you don't want to run the whole pipeline — for example, to re-render an existing work directory after a manual edit, to inspect what `fetch` produces, or to launch the editor on an old job.

The CLI is `paper_video.py` next to this `SKILL.md`. Subcommands: `fetch`, `render`, `edit`.

## When to Use

- "Re-render this work directory" — call `render` directly
- "Open the editor on `paper-video-output/<slug>`" — call `edit --work <dir>`
- "Just fetch the PDF + text from this URL" — call `fetch` and stop
- "Render with a different voice without re-running the agents" — call `render --voice-name <name>`

## When NOT to use

- "Make a video from this paper" → use the `/paper-video-studio:paper-video` orchestrator instead. It runs the full agent pipeline including truth-checking.

## Prerequisites (one-time)

```bash
pip install -r "${CLAUDE_PLUGIN_ROOT}/skills/paper-cli/requirements.txt"
```

`ffmpeg` and `ffprobe` must be on PATH (already present on this machine).

## Workflow

The skill is a two-step CLI: `fetch` (download + extract), then `render` (build the video). Between them, Claude (you) writes a small `points.json` listing the key passages to highlight.

### Step 1 — Fetch

```bash
python "C:\Users\roscoe\.claude\skills\paper-video\paper_video.py" fetch <input> --out <work_dir>
```

`<input>` can be:
- A PubMed URL (`https://pubmed.ncbi.nlm.nih.gov/12345678/`)
- A bare PMID (`12345678`)
- A PMC URL or PMCID (`PMC1234567`)
- A direct PDF URL (`https://.../paper.pdf`)
- A local PDF path

This produces in `<work_dir>/`:
- `paper.pdf` — the source PDF
- `meta.json` — title, authors, journal, year, DOI/PMID/PMCID
- `pages.json` — per-page text (use this to pick key passages)

If a PMID is given but no free PMC PDF exists, the script fails fast. Ask the user for a local PDF in that case.

### Step 2 — Decide the key points

If the user **provided key points**, normalize them to a `points.json` like below.

If they did **not**, read `pages.json` and pick **3–7 key passages** that represent the paper's most important findings (effect size, primary outcome, surprising results, headline conclusion). Then write:

```json
[
  {
    "text": "verbatim quote from the PDF, ideally one sentence or a short phrase",
    "narration": "natural spoken sentence explaining this passage in the speaker's voice"
  },
  ...
]
```

Save it to `<work_dir>/points.json`.

**Quote rules (critical):**
- `text` MUST appear verbatim in the PDF. The locator does an exact substring search first, then a fuzzy word-sequence fallback — but unique multi-word phrases work best.
- Prefer the most distinctive 8–20 words of the sentence. Avoid quoting cross-line text that includes hyphenation.
- If a passage you want isn't searchable verbatim, pick a different sentence from the same paragraph.
- Anything the locator can't find is **logged as a warning and skipped** — the video still renders without that highlight.

**Narration rules:**
- Sound like a human podcast host, not a robot reading a quote. Paraphrase or contextualize.
- 1–3 sentences per point. The clip auto-extends to fit the voiceover.
- Don't say "quote" or "the paper says" repeatedly — just present the finding.

### Step 3 — Render

```bash
python "C:\Users\roscoe\.claude\skills\paper-video\paper_video.py" render \
  --work <work_dir> \
  --out <work_dir>\paper_video.mp4 \
  --voice edge
```

Options:
- `--voice edge` (default) — narrated with edge-tts. `--voice none` for a silent video.
- `--voice-name en-US-AriaNeural` (default). Other good choices: `en-US-GuyNeural`, `en-GB-RyanNeural`, `en-AU-NatashaNeural`. Full list: `edge-tts --list-voices`.
- `--keep` — don't delete the intermediate frames directory (useful for debugging).

Output is an MP4 at 1920×1080, 30fps, H.264 + AAC.

### Step 4 — Report

Tell the user the path. If they're on Windows and want to preview, `start "" <path>` opens it in the default player.

### Step 5 — Edit (optional)

The skill ships with a Tkinter desktop editor for revising `points.json` after the agents finish. Launch:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/paper-cli/paper_video.py" edit --work <work_dir>
```

The editor supports:
- Picking quote text by selecting it from the extracted page view.
- Editing narration per point.
- Adding, removing, and reordering points.
- Auto-snapshot versioning on every Save, plus named versions via "Save as version…".
- Rendering directly from the editor with a voice picker.

When invoked inside the `paper-video-studio` plugin via `/paper-video`, the orchestrator offers to launch the editor between flow-editor and render. Users can also launch it standalone at any time pointing at any work directory that has at least `pages.json`.

## End-to-End Example

```bash
# 1. Fetch a PubMed paper
python "C:\Users\roscoe\.claude\skills\paper-video\paper_video.py" fetch \
  https://pubmed.ncbi.nlm.nih.gov/30957449/ --out .\work_30957449

# 2. (you read work_30957449\pages.json and write points.json)

# 3. Render
python "C:\Users\roscoe\.claude\skills\paper-video\paper_video.py" render \
  --work .\work_30957449 --out .\work_30957449\summary.mp4 --voice edge
```

## Failure Modes

- **"No free PDF available for PMID …"** — PMID is not open-access on PMC. Ask the user for a local PDF or a PMCID.
- **"Could not locate quote: …"** — your `text` doesn't substring-match the PDF. Re-check the wording (especially en-dashes, ligatures, hyphenation). The clip is skipped but the video still completes.
- **edge-tts blocks or errors** — usually rate-limit or transient network. Re-run, or pass `--voice none` for a silent build.
- **ffmpeg concat fails** — usually disk space or codec mismatch. Delete `<work_dir>\tmp` and re-render.

## Notes on Aesthetics

- The background letterbox color is `#121620`, the highlight is yellow (semi-transparent fill + opaque amber outline).
- Title card holds for `max(4s, narration_length + 0.5s)`; per-point clips are `max(5s, narration_length + 1s)`.
- Pan + zoom uses an ease-in-out curve over the first ~45% of each clip, then holds on the highlight.
