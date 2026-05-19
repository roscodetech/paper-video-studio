---
name: paper-video
description: Convert a PubMed/PMC/PDF paper into a fact-checked narrated educational video via the 5-agent pipeline.
argument-hint: <url|pmid|pmcid|pdf-path>
---

You are the orchestrator for paper-video-studio. Drive the pipeline end-to-end.

The plugin root contains `skills/paper-cli/paper_video.py`. Resolve the absolute path to that file from `${CLAUDE_PLUGIN_ROOT}/skills/paper-cli/paper_video.py`. If `CLAUDE_PLUGIN_ROOT` is not available in the environment, locate the plugin root by inspecting your installation (the directory containing `.claude-plugin/plugin.json` and `commands/paper-video.md`). For brevity, refer to the resolved path as `<cli>` below.

## Step 1 — Fetch

Determine a work directory: `./paper-video-output/<slug>/` where slug is derived from the input (sanitize spaces, lowercase, max 40 chars).

Run:
```bash
python <cli> fetch "$ARGUMENTS" --out "<work_dir>"
```

Verify `<work_dir>/meta.json`, `<work_dir>/pages.json`, `<work_dir>/paper.pdf` exist.

If fetch fails (e.g. "No free PDF available for PMID …"), halt and ask the user for a local PDF path.

## Step 2 — Curate

Spawn the `paper-curator` subagent. In the prompt, tell it the work directory and ask it to follow its instructions.

After the agent returns, verify `<work_dir>/candidates.json` exists and has 5-7 entries. If fewer than 3, halt with a message: "Curator returned too few candidates — open the editor (`python <cli> edit --work <work_dir>`) to pick passages manually."

## Step 3 — Hook

Spawn the `hook-writer` subagent with the work directory. Verify `hook.json` exists and has all five fields (hook_line, angle, tone, target_audience, anchor_candidate_idx).

## Step 4 — Script

Spawn the `script-writer` subagent with the work directory. This is its first-pass mode (no truth_report.json yet). Verify `points.json` exists.

## Step 5 — Truth-check (with one retry)

Spawn the `truth-checker` subagent. Read `truth_report.json`.

If `status == "pass"`: proceed to Step 6.

If `status == "fail"`:
1. Spawn `script-writer` again. It will see `truth_report.json` and rewrite only the flagged lines.
2. Re-spawn `truth-checker`.
3. If second-pass `status == "fail"`: HALT. Output the contents of `truth_report.json` and tell the user: "Two truth-check passes failed. Open the editor to fix manually: `python <cli> edit --work <work_dir>`. After fixes, ask me to continue from Step 6."

## Step 6 — Flow

Spawn the `flow-editor` subagent. Read `flow_report.json` and surface the `hook_strength` score to the user. Note any revisions applied.

## Step 7 — Optional editor review

Ask the user:
> "Hook strength: <N>/10. Open the Tkinter editor for final review before render? [y/n]"

If yes: run `python <cli> edit --work <work_dir>` and wait for the user to close the editor before continuing.

## Step 8 — Render

Run:
```bash
python <cli> render --work "<work_dir>" --out "<work_dir>/paper_video.mp4" --voice edge
```

Report the path. On Windows, suggest `start "" "<path>"` to preview.

## Failure mode summary

- Curator returns < 3 candidates → halt + editor suggestion.
- Truth-checker fails twice → halt + editor suggestion.
- Render fails → surface ffmpeg error + suggest `--voice none` retry.
