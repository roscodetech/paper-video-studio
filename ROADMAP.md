# Roadmap

Ideas and known limitations for future versions. Not committed work — these are signals about where the plugin could grow.

## Highlight rendering

### Font-size-aware line heights
Today `_normalize_line_heights` picks a single canonical half-height and applies it to every line of a matched quote. That's the right call when the quote is entirely within one paragraph of body text (the common case), but if a quote ever spans a font-size boundary — body text plus a section heading, or a figure caption inline with body — every line gets the same outline height regardless of font size. The taller-font lines will look slightly cramped.

Fix shape: cluster matched lines by their median word height first, then compute a per-cluster canonical half-height instead of one for the whole quote. Roughly 10 lines of code in `_normalize_line_heights`.

Triggered if/when a user reports a quote that visibly spans multiple font sizes and the highlights look off.

## Pipeline

### `/paper-video --resume <work_dir>`
After a truth-checker double-failure halt, the user currently has to manually re-run from step 6 in chat. A `--resume` flag would skip steps that already produced their output JSON and pick up where the pipeline stopped. Listed as v0.2 in `docs/superpowers/specs/2026-05-18-paper-video-studio-design.md` §10.

### Per-platform aspect ratios
v1 is 16:9 only. Reels/TikTok/Shorts need 9:16. Either a `--aspect 9x16` flag on `render`, or a separate `reels-render` subcommand that crops the centre column from the existing 16:9 output. Spec §10.

### Auto-thumbnail generation
Pick the highest-`hook_strength` frame from the rendered video and export as a `thumb.jpg` alongside the MP4. Spec §10.

### Direct upload to YouTube / TikTok / Reels
Out of scope for v1. Spec §10.

### A/B testing different hooks against the same paper
Spec §10.

### Multi-language narration
edge-tts supports many voices; the script-writer agent would need an optional `--language` flag and matching prompt adjustments. Spec §10.

### Subagent parallelization
truth-checker and flow-editor are serial in v1. They could run in parallel after script-writer completes (flow-editor would need to handle the case where truth-checker fixes are still pending — easiest fix: serial stays).

### Custom voice cloning
edge-tts neural voices only in v1. Cloning would mean integrating ElevenLabs or Coqui.
