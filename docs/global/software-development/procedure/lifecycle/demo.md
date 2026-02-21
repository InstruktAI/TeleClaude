---
id: 'software-development/procedure/lifecycle/demo'
type: 'procedure'
domain: 'software-development'
scope: 'project'
description: 'Celebrate delivered work with a visual demo presented by the AI. Mandatory after every finalize.'
---

# Demo — Procedure

## Goal

Celebrate every delivery with a visual, engaging presentation of what was built. The demo is the team's reward for completing the build-review-finalize gauntlet. Every demo is a feast.

## Preconditions

- Finalize phase completed successfully (merged to main, delivery logged).
- Worktree and todo artifacts still exist (cleanup happens AFTER the demo).

## Steps

1. **Gather the story.** Read from the todo folder:
   - `requirements.md` — what was asked for
   - `implementation-plan.md` — how it was approached
   - `review-findings.md` — what the review caught and what was fixed
   - `quality-checklist.md` — final gate status
   - `git log` on the branch — the commit narrative

2. **Compose the demo.** Build a presentation covering:

   **Act 1 — The Challenge**
   What problem did this solve? Frame it from the user's perspective.
   One paragraph, no jargon.

   **Act 2 — The Build**
   Key architectural decisions. What was created, modified, wired together.
   Highlight the most interesting technical choice.

   **Act 3 — The Gauntlet**
   Review rounds survived. Critical findings caught and fixed.
   Frame it as quality earned, not rework endured.

   **Act 4 — The Numbers**
   Metrics that tell the story:
   - Commits made
   - Files changed (created / modified)
   - Tests added or passing
   - Review rounds / findings resolved
   - Lines of code (net delta)

   **Act 5 — What's Next**
   Non-blocking suggestions carried forward. Ideas sparked.
   What this unlocks for the roadmap.

3. **Present.** Use the richest renderer available in the current environment.
   Structured widgets, rich cards, interactive documents — whatever the platform
   supports. Each act becomes a distinct section. The metrics table should be
   scannable at a glance. Include a code highlight if one decision deserves it.
   Close with the merge commit hash and delivery date.

   When no rich renderer exists, fall back to well-formatted markdown.
   The content matters more than the medium — a plain-text feast still counts.

4. **Archive.** Create a durable demo artifact:
   - Determine the sequence number from existing `demos/*/` folders + 1. Zero-pad to 3 digits.
   - Create `demos/{NNN}-{slug}/` directory.
   - Write `snapshot.json` with captured metrics, narrative data, and the current project version from `pyproject.toml`.
   - Generate `demo.sh` render script with semver gate: the script checks major version compatibility before executing, prints a message and exits 0 on mismatch.
   - Commit the demo folder before cleanup removes the source data.
   - See `project/spec/demo-artifact` for the full schema.

## Outputs

- A demo presentation delivered to the user through the best available channel.
- Smiles.

## Recovery

- If artifacts are already cleaned up, reconstruct from `git log` and `delivered.md`.
