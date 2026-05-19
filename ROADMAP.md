# Roadmap

Ideas and known limitations for future versions. Not committed work — these are signals about where the plugin could grow.

## Suggested next milestone (v0.2.0)

Three items that, together, unlock multi-platform distribution and brand consistency. Logo + aspect-ratio matrix + richer title cards.

### Logo on intro and outro slides
Foundational for brand consistency when producing videos for an agency or org (Skinvest, Roscode, etc.). Configure via the editor or a sidecar file:

```json
{
  "logo_path": "C:/path/to/skinvest-logo.png",
  "logo_position": "top-right",
  "logo_size_pct": 8
}
```

Rendered as a PNG overlay (alpha-aware) on the title and end frames. Position options: `top-left | top-right | bottom-left | bottom-right`. Size as percent of video width (so it scales with aspect ratio). Low effort, high perceived polish.

### Aspect-ratio matrix
v1 is 16:9 (1920×1080) only. Multi-platform distribution needs:

| Ratio | Pixels | Where it ships |
|---|---|---|
| 16:9 | 1920×1080 | YouTube, desktop, current default |
| 9:16 | 1080×1920 | Reels, TikTok, Shorts |
| 1:1 | 1080×1080 | Instagram feed, LinkedIn carousel |
| 4:5 | 1080×1350 | Instagram feed taller |

CLI flag: `--aspect 16x9 | 9x16 | 1x1 | 4x5`. The pan logic and highlight viewport are already in normalized coords, so the bigger work is **per-aspect title/outro frame layouts** (centering, font sizing, line wrapping for narrower formats) plus rebalancing camera zoom levels (a 9:16 viewport on a portrait PDF page wants a different zoom curve than a 16:9 viewport).

### Richer title card
Image-10-vs-image-11 problem: the source PDF cover has organization, date, document number, agenda item, title — our title frame has only the title in white on dark. Two ship options:

**Option A — Enrich the existing title frame.** Add fields below the title: source organization, date, document number/citation, authors. Same dark-bg minimalist style; just more context. Pull from `meta.json`'s existing fields plus a new `source_org` / `document_id` pair. Low complexity. This is the recommended ship.

**Option B — PDF-cover intro slide.** Render the first page of the PDF as a brief intro frame, optionally with a pan/zoom that lands on the title. Works well for documents with a designed cover (WHO resolutions); less well for PubMed abstracts that start straight into body text. Higher complexity; likely a per-document opt-in (`--intro pdf-cover`).

## Highlight rendering

### Font-size-aware line heights
Today `_normalize_line_heights` picks a single canonical half-height and applies it to every line of a matched quote. That's the right call when the quote is entirely within one paragraph of body text (the common case), but if a quote ever spans a font-size boundary — body text plus a section heading, or a figure caption inline with body — every line gets the same outline height regardless of font size. The taller-font lines will look slightly cramped.

Fix shape: cluster matched lines by their median word height first, then compute a per-cluster canonical half-height instead of one for the whole quote. Roughly 10 lines of code in `_normalize_line_heights`.

Triggered if/when a user reports a quote that visibly spans multiple font sizes and the highlights look off.

## Pipeline

### `/paper-video --resume <work_dir>`
After a truth-checker double-failure halt, the user currently has to manually re-run from step 6 in chat. A `--resume` flag would skip steps that already produced their output JSON and pick up where the pipeline stopped. Listed as v0.2 in `docs/superpowers/specs/2026-05-18-paper-video-studio-design.md` §10.

### Auto-thumbnail generation
Pick the highest-`hook_strength` frame from the rendered video and export as a `thumb.jpg` alongside the MP4. Useful as a YouTube thumbnail and as the social-card preview. Spec §10.

### Direct upload to YouTube / TikTok / Reels
Out of scope for v1. Each platform has its own auth and constraints (TikTok needs a long-form app review). Cleanest path is a separate `paper-publisher` plugin later. Spec §10.

### A/B testing different hooks against the same paper
Re-spawn hook-writer with explicit angle constraints (`scale-of-burden` vs `tractability-twist` vs `policy-shift`), render N versions, pick a winner. Spec §10.

### Multi-language narration
edge-tts supports many voices; the script-writer agent would need an optional `--language` flag and matching prompt adjustments. Spec §10.

### Subagent parallelization
truth-checker and flow-editor are serial in v1. They could run in parallel after script-writer completes (flow-editor would need to handle the case where truth-checker fixes are still pending — easiest fix: serial stays).

### Custom voice cloning
edge-tts neural voices only in v1. Cloning would mean integrating ElevenLabs or Coqui.
