# Changelog

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
