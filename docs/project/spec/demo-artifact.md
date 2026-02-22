---
id: 'project/spec/demo-artifact'
type: 'spec'
scope: 'project'
description: 'Demo artifact format: slug-based folders with snapshot.json containing a runnable demo command.'
---

# Demo Artifact — Spec

## What it is

Each delivery produces a demo artifact in `demos/`. Artifacts are committed to git and gated by semver. Demos are created during the build phase and verified by the reviewer.

## Canonical fields

### Folder convention

`demos/{slug}/` — slug-based naming with no sequence numbers.

### snapshot.json schema

```json
{
  "slug": "string",
  "title": "string",
  "version": "string (semver from pyproject.toml)",
  "delivered": "string (YYYY-MM-DD)",
  "commit": "string (merge commit hash)",
  "demo": "string (optional shell command executed from demo folder)",
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

### Demo field

The `demo` field is an optional shell command string that demonstrates the feature. The command is executed with `shell=True` from the demo folder directory as the current working directory. If absent, the runner warns and skips execution (backward compatibility).

## Known caveats

- Demo artifacts survive cleanup (they live outside `todos/{slug}/`)
- Breaking major version bumps disable stale demos automatically via the semver gate
- No retroactive demo generation for past deliveries
- Existing demos may use variant field names (`delivered_date` instead of `delivered`, etc.) — the CLI runner handles these with fallbacks
- Delivery log is `todos/delivered.yaml`, not `delivered.md`
