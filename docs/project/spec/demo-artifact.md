---
id: 'project/spec/demo-artifact'
type: 'spec'
scope: 'project'
description: 'Demo artifact format: slug-based folders with snapshot.json and demo.md.'
---

# Demo Artifact — Spec

## What it is

Each delivery produces a demo artifact in `demos/`. Artifacts are committed to git and gated by semver. Demos are created during the build phase and verified by the reviewer.

## Canonical fields

### Folder convention

`demos/{slug}/` — slug-based naming with no sequence numbers.

### demo.md

The primary demonstration artifact. Required sections:

| Section                  | Content                                                   |
| ------------------------ | --------------------------------------------------------- |
| `# Demo: {title}`        | H1 with the delivery title.                               |
| `## Validation`          | Executable bash code blocks that prove the feature works. |
| `## Guided Presentation` | Sequential walkthrough steps for the AI presenter.        |

#### Validation

Fenced ` ```bash ` blocks are extracted and run sequentially by `telec todo demo {slug}`. All must exit 0 for the build gate to pass.

- Blocks preceded by `<!-- skip-validation: reason -->` are skipped by the validator but reported for visibility.
- The validator prepends the project's `.venv/bin` to PATH so `python` resolves to the project environment.

#### Guided Presentation

A continuous sequence of steps the AI presenter walks through: what to do, what to observe, why it matters. Each step is a natural unit — operate, show, explain — not split into separate concerns. The presenter reads this top-to-bottom and executes.

#### Non-destructive rule

Demos run on real data. They must never be destructive. CRUD demos create their own test data, demonstrate the behavior, and clean up after themselves.

### snapshot.json schema

```json
{
  "slug": "string",
  "title": "string",
  "version": "string (semver from pyproject.toml)",
  "delivered": "string (YYYY-MM-DD)",
  "commit": "string (merge commit hash)",
  "metrics": {
    "commits": "integer",
    "files_changed": "integer",
    "files_created": "integer",
    "tests_added": "integer",
    "tests_passing": "integer",
    "review_rounds": "integer",
    "findings_resolved": "integer",
    "lines_added": "integer",
    "lines_removed": "integer"
  },
  "acts": {
    "challenge": "string (markdown)",
    "build": "string (markdown)",
    "gauntlet": "string (markdown)",
    "whats_next": "string (markdown)"
  }
}
```

The `demo` field (shell command string) is deprecated. New demos use `demo.md` instead. The CLI runner falls back to the `demo` field when `demo.md` is absent (backward compatibility).

## Known caveats

- Demo artifacts survive cleanup (they live outside `todos/{slug}/`)
- Breaking major version bumps disable stale demos automatically via the semver gate
- No retroactive demo generation for past deliveries
- Existing demos may use variant field names (`delivered_date` instead of `delivered`, etc.) — the CLI runner handles these with fallbacks
- Delivery log is `todos/delivered.yaml`, not `delivered.md`
