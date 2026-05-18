# Changelog

## 0.1.4 — 2026-05-19

Improved: highlight reveal is now smooth and synced with narration. Previously each clip ran pan (no highlight, ~45% of clip) → word-by-word reveal (~25%) → hold. The reveal arrived seconds after narration started and popped in discrete word steps. Now the pan is a fixed ~1.1s and runs in parallel with a pixel-smooth left-to-right wipe; the highlight is fully visible right as the pan settles, and the rest of the clip is one long held frame with the full highlight on screen. The wipe still terminates word-aligned at the held end because the underlying bboxes are word-bridged, so paused frames at the hold position never cut a word.

## 0.1.3 — 2026-05-19

Improved: highlight boundaries now snap to natural clause/sentence breaks. After the matched word sequence, the locator looks ahead up to 6 words for a word ending in `.,;:!?—)` and extends the highlight to include it. If the matched range would otherwise end on a weak word (preposition, article, conjunction, auxiliary) and no punctuation is within reach, the range is bumped forward by one word so the highlight never terminates on "of", "the", "and", etc. Paragraph breaks (large vertical jumps) stop the extension.

## 0.1.2 — 2026-05-19

Fixed: the highlight could end mid-word (e.g. "skin d…" instead of "skin diagnoses") during animation or at the held end-frame. The locator now does word-sequence matching against `page.get_text("words")` and returns word-level bboxes bridged horizontally, and the animation reveals whole words at a time. The amber outline is drawn once per visible line so there are no vertical strokes between adjacent words.

## 0.1.1 — 2026-05-19

Fixed: title cards on rendered videos showed the PDF filename stem (e.g. `A78_R15-en`) when the source PDF lacked proper metadata. The editor now exposes Title and Authors fields in a top bar; values are written to `meta.json` on Save and again immediately before Render, so the title card always reflects the latest user input.

## 0.1.0 — 2026-05-18

Initial release.

- 5-agent pipeline: paper-curator, hook-writer, script-writer, truth-checker, flow-editor.
- `/paper-video <url>` orchestrator slash command.
- Tkinter editor with selectable page text, dirty tracking, auto-snapshot + named version history, render-with-status.
- Nested `paper-video` skill: `fetch`, `render`, `edit` subcommands.
- Truth-checker veto with one auto-fix retry.

### Verification at 0.1.0

End-to-end pipeline manually validated against the WHO WHA78.15 resolution PDF:
- fetch → meta.json, pages.json, paper.pdf (5 pages)
- curator → candidates.json with 6 verbatim passages
- hook → hook.json with scale-of-burden angle
- script → points.json with 6 narrated points
- truth-check → pass (all claims defensible)
- flow → hook_strength 8/10, no revisions needed
- render → 80.6s MP4, 6 points narrated successfully

Truth-checker fail-case JSON schema fixture committed at `paper-video-output/wha78-r15-e2e/overclaim_test/` for regression reference (DALYs misframed as deaths).

12/12 pytest assertions pass.

### Gated for user

- Removing standalone `~/.claude/skills/paper-video/` before plugin install.
- Local plugin install via `claude plugin add file://...`.
- GitHub publish + v0.1.0 tag.
