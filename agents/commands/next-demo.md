---
argument-hint: '[slug]'
description: Celebrate delivery with a demo artifact and rich widget presentation
---

# Demo

You are now the Presenter.

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/demo.md

## Purpose

Capture a data snapshot from todo artifacts and git, generate a render script, present the demo via widget, and commit the result.

## Inputs

- Slug: "$ARGUMENTS"
- Worktree for the slug (artifacts must still exist — demo runs before cleanup)

## Outputs

- `demos/{NNN}-{slug}/snapshot.json` — captured metrics and narrative data
- `demos/{NNN}-{slug}/demo.sh` — executable render script with semver gate
- Widget rendered to the current session
- Report format:

  ```
  DEMO COMPLETE: {slug}

  Artifact: demos/{NNN}-{slug}/
  Widget: rendered
  ```

## Steps

1. **Determine sequence number.** Count existing `demos/*/` folders and add 1. Zero-pad to 3 digits (e.g., `001`, `002`).

2. **Read todo artifacts** from `todos/{slug}/`: `requirements.md` (Goal section for Act 1), `implementation-plan.md` (overview for Act 2), `review-findings.md` (criticals for Act 3, if exists), `quality-checklist.md` (gate status), `state.json` (review rounds, findings data).

3. **Gather git metrics** from the merge commit: `git log --oneline main~1..main` (commit count), `git diff --stat main~1..main` (files changed, lines), `git diff --diff-filter=A --name-only main~1..main` (files created), `git log --oneline main~1..main -- "tests/"` (tests added).

4. **Read delivery context.** `todos/delivered.md` for title and date (latest entry matching slug). Project version from `pyproject.toml`. Merge commit hash: `git log -1 --format=%h main` (the merge commit itself).

5. **Compose snapshot.json** per the demo-artifact spec with slug, title, sequence, version, delivered date, commit hash, metrics object, and acts object.

6. **Compose the five acts.** Act 1 (Challenge): one paragraph, user's perspective, from requirements Goal. Act 2 (Build): most interesting technical choice, from implementation-plan overview + git diff stat. Act 3 (Gauntlet): quality earned, from review-findings criticals found/fixed. Act 4 (Numbers): metrics table from git + state.json. Act 5 (What's Next): non-blocking suggestions, future work. Tone: celebratory but specific, let numbers speak, no fluff.

7. **Generate demo.sh.** Executable bash script that reads `snapshot.json` from its own directory, compares major version against current `pyproject.toml`, exits 0 on mismatch with a message, and falls back to formatted terminal output (jq + printf) when no daemon API is available. `chmod +x` the script.

8. **Write files.** Create `demos/{NNN}-{slug}/` directory, write `snapshot.json` and `demo.sh`.

9. **Render widget** via `teleclaude__render_widget` with title, status "success", text sections for Acts 1-3 and 5 (with dividers between), table section for Act 4 metrics (headers: Metric, Value), optional code section for a technical highlight, and footer with commit hash, delivery date, and version.

10. **Commit.** `git add demos/{NNN}-{slug}/` and commit with message `feat(demo): {slug} delivery celebration`.

- If todo artifacts are already cleaned up, reconstruct from `git log` and `todos/delivered.md`.
- Demo failure is non-blocking — log a warning and exit cleanly.
