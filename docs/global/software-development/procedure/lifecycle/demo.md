---
id: 'software-development/procedure/lifecycle/demo'
type: 'procedure'
domain: 'software-development'
scope: 'project'
description: 'Create runnable demo artifacts during build and present them to celebrate delivery.'
---

# Demo — Procedure

## Goal

Celebrate every delivery with a runnable demonstration of what was built. Demos are created during the build phase and presented after merge to celebrate the work. Every demo is a feast.

## Creation (Builder)

Demos are created during the build phase as a deliverable, verified by the reviewer, and committed alongside the implementation.

### When to create

During the build phase, after implementing the feature and before completing the build gates.

### How to create

1. **Create demo folder.** `demos/{slug}/` (slug-based naming, no sequence numbers).

2. **Compose snapshot.json.** Capture the delivery story with:
   - Slug, title, version (from `pyproject.toml`)
   - Delivered date, commit hash (will be merge commit after finalize)
   - Metrics (commits, files changed, tests, review rounds, findings, lines)
   - Five Acts narrative (see structure below)
   - `demo` field: shell command that demonstrates the feature

3. **The Five Acts structure** (captured in `acts` object):

   **Act 1 — The Challenge**
   What problem did this solve? Frame it from the user's perspective.
   One paragraph, no jargon.

   **Act 2 — The Build**
   Key architectural decisions. What was created, modified, wired together.
   Highlight the most interesting technical choice.

   **Act 3 — The Gauntlet**
   Review rounds survived. Critical findings caught and fixed.
   Frame it as quality earned, not rework endured.

   **Act 5 — What's Next** (stored as `whats_next` field)
   Non-blocking suggestions carried forward. Ideas sparked.
   What this unlocks for the roadmap.

   Act 4 (The Numbers) is rendered from the metrics object, not written as narrative.

4. **The demo field.** A shell command string that demonstrates the feature. Examples:
   - `echo "Feature demo: run 'telec todo create my-slug' to see the scaffolding"`
   - `python demos/my-feature/show_demo.py`
   - `cat README.md | grep "New feature"`

   The command is executed with `shell=True` from the demo folder as current working directory.

5. **Write and commit.** Save `demos/{slug}/snapshot.json` and include it in a commit during the build phase.

### Builder guidance

The demo is part of the definition of done. Do not skip it. The demo field does not need to be elaborate — a simple command that shows the feature working is sufficient. The snapshot narrative tells the story; the demo command proves it works.

## Presentation

Demos are presented to celebrate delivery, either via conversational AI or CLI.

### Conversational presentation (/next-demo)

- **No slug**: AI lists available demos and asks which one to present.
- **With slug**: AI runs `telec todo demo <slug>`, then renders a celebration widget with the snapshot data (title, acts, metrics table).

### CLI presentation (telec todo demo)

- **No slug**: lists all available demos (table format: slug, title, version, delivered date).
- **With slug**: executes the `demo` field command for that demo.

## Schema

See `project/spec/demo-artifact` for the full `snapshot.json` schema.

## Recovery

- Demos survive cleanup (they live in `demos/{slug}/`, not `todos/{slug}/`).
- If a demo is missing the `demo` field, the runner warns and skips execution (backward compatibility).
- Breaking major version bumps disable stale demos automatically via semver gate.
