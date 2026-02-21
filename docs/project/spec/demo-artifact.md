---
id: 'project/spec/demo-artifact'
type: 'spec'
scope: 'project'
description: 'Demo artifact format: numbered folders with snapshot.json and demo.sh for celebrating deliveries.'
---

# Demo Artifact — Spec

## What it is

Each delivery produces a demo artifact in `demos/`. Artifacts are committed to git and gated by semver.

## Canonical fields

### Folder convention

`demos/NNN-{slug}/` where NNN is a zero-padded sequence number derived from count of existing `demos/*/` folders + 1.

### snapshot.json schema

```json
{
  "slug": "string",
  "title": "string",
  "sequence": "integer",
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

### demo.sh contract

A bash script that:

1. Reads `snapshot.json` from its own directory (`$(dirname "$0")/snapshot.json`)
2. Reads the current project version from `pyproject.toml`
3. Compares major versions — if incompatible, prints a message and exits 0
4. Renders the demo via `render_widget` (curl to daemon API) or falls back to formatted terminal output (jq + printf)
5. Must be `chmod +x`

## Known caveats

- Demo artifacts survive cleanup (they live outside `todos/{slug}/`)
- Breaking major version bumps disable stale demos automatically via the semver gate
- No retroactive demo generation for past deliveries
