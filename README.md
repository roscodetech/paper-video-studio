# paper-video-studio

Convert PubMed/PMC/PDF scientific papers into fact-checked, hook-driven, narrated educational videos via a Claude Code plugin.

## What it does

`/paper-video <url>` runs a 5-agent pipeline:

1. **paper-curator** picks 5-7 newsworthy verbatim passages.
2. **hook-writer** writes the opening line and sets the script's angle and tone.
3. **script-writer** writes podcast-style narration for every point.
4. **truth-checker** validates every claim against the paper. Vetoes overclaim; one auto-fix retry, then halt.
5. **flow-editor** judges pacing and hook strength, may revise narration.

Then the existing `paper-video` skill renders an MP4 (1920x1080, narrated via edge-tts). A Tkinter editor is available for manual override at any stage.

## Install

```bash
# Remove the standalone skill if previously installed:
rm -rf ~/.claude/skills/paper-video

# Add the plugin:
claude plugin add github.com/roscodetech/paper-video-studio
```

Local development install:
```bash
claude plugin add "file://C:/ROSCODE TECH/paper-video-studio"
```

## Prerequisites

```bash
pip install -r skills/paper-video/requirements.txt
```

You need `ffmpeg` and `ffprobe` on PATH for rendering.

## Usage

```
/paper-video https://pubmed.ncbi.nlm.nih.gov/30957449/
```

Other accepted inputs:
- PubMed URL
- Bare PMID
- PMC URL or PMCID
- Direct PDF URL
- Local PDF path

## Standalone editor

```bash
python skills/paper-video/paper_video.py edit --work <work_dir>
```

Requires `<work_dir>/pages.json` (created by `fetch`).

## Output

The pipeline writes everything to `./paper-video-output/<slug>/`:
- `paper.pdf`, `meta.json`, `pages.json` — fetched inputs
- `candidates.json`, `hook.json`, `points.json`, `truth_report.json`, `flow_report.json` — agent outputs
- `points_history/` — auto-snapshots and named versions of `points.json`
- `paper_video.mp4` — final video

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "No free PDF available for PMID …" | PMID not on PMC | Pass a local PDF path instead. |
| "Could not locate quote: …" during render | Quote text doesn't match PDF verbatim | Re-run editor; use the "Use selection as quote" button on the actual page text. |
| Two truth-check passes failed | Hook or narration overclaim is unresolvable by agent | Open editor (`python paper_video.py edit --work <dir>`), revise narration manually, then ask Claude to continue from Step 6. |

## Development

Tests:
```bash
python -m pytest tests/ -v
```

## Roadmap

Known limitations and potential upgrades are tracked in [`ROADMAP.md`](./ROADMAP.md). Highlights:

- **Font-size-aware line heights** — quotes that span multiple font sizes (body + heading) currently use a single canonical outline height. Fine for body-text quotes; worth revisiting if a heading-spanning quote ever needs it.
- **`/paper-video --resume`** — pick up after a truth-checker halt without re-running earlier stages.
- **9:16 render** — Reels/TikTok aspect ratio variant.

## License

MIT — see `LICENSE`.
