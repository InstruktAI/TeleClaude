---
id: 'general/spec/tools/telec-cli'
type: 'spec'
scope: 'global'
description: 'Canonical AI-safe telec commands: project init, docs sync, and todo scaffolding.'
---

# Telec CLI Tool — Spec

## What it is

AI-safe `telec` commands for project work. Run `telec --help` for full options.

## Canonical fields

### Docs sync

```bash
telec sync
telec sync --validate-only
telec sync --warn-only
telec sync --project-root /path/to/project
```

### Todo scaffolding

```bash
telec todo create config-schema-validation
telec todo create auth-hardening --after config-schema-validation,job-contract-refinements
telec todo create auth-hardening --project-root /path/to/project
telec todo validate [slug]
```

Creates: `todos/{slug}/requirements.md`, `implementation-plan.md`, `quality-checklist.md`, `state.json`.
Validation: checks `state.json` schema and requires files for "Ready" status (score >= 8).

### Project init

```bash
telec init
```

Rerun after hook/watcher artifact changes.
