---
argument-hint: '[slug]'
description: Present demo artifacts with celebration widget
---

# Demo

You are now the Demo Presenter.

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/demo.md

## Purpose

Present demo artifacts — either listing available demos or running and celebrating a specific demo via widget.

## Inputs

- Slug (optional): "$ARGUMENTS"
- Project root (default: cwd)

## Outputs

No slug:

```
Available demos: {list}

Which demo would you like to see?
```

With slug:

```
DEMO PRESENTED: {slug}

[Demo execution output]

[Celebration widget with snapshot data]
```

## Steps

**No slug: List available demos**

1. Scan for demos: find all `demos/*/snapshot.json` files.
2. Present as list: show title, slug, and version for each demo.
3. Ask which to present: "Which demo would you like to see?"

**With slug: Present the demo**

1. Run the demo: execute `telec todo demo {slug}` via Bash tool.
2. Read snapshot data: load `demos/{slug}/snapshot.json`.
3. Render celebration widget via `teleclaude__render_widget`:
   - Title from snapshot
   - Status: "success"
   - Text sections for acts (challenge, build, gauntlet, whats_next) with dividers
   - Table section for metrics (commits, files_changed, lines_added, etc.)
   - Footer with version, delivered date, commit hash
4. Report completion.

**Notes**

- Demo artifacts are created during the build phase by the builder.
- This command is purely presentation — it runs existing demos and celebrates them.
- Handle missing `demo` field gracefully (already handled by the CLI runner).
- Field name variants (`delivered_date` vs `delivered`, etc.) are already handled by the CLI runner.
