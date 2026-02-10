---
id: 'general/spec/tools/telec-cli'
type: 'spec'
scope: 'global'
description: 'Canonical AI-safe telec commands: project init, docs sync, and todo scaffolding.'
---

# Telec CLI Tool — Spec

## What it is

Defines the minimal `telec` commands that AI workers should use during normal project work.

## Canonical fields

- Binary: `telec`
- Project root behavior: defaults to current working directory unless `--project-root` is provided.

### Project setup and docs operations

- Initialize project hooks, watchers, and docs sync:

```bash
telec init
```

- Validate/build/sync docs artifacts:

```bash
telec sync
telec sync --validate-only
telec sync --warn-only
telec sync --project-root /path/to/project
```

### Todo scaffolding commands (`telec todo`)

- Create todo skeleton:

```bash
telec todo create config-schema-validation
```

- Create in another project root:

```bash
telec todo create auth-hardening --project-root /path/to/project
```

- Create with dependencies:

```bash
telec todo create auth-hardening --after config-schema-validation,job-contract-refinements
```

- Files created by `telec todo create <slug>`:
  - `todos/{slug}/requirements.md`
  - `todos/{slug}/implementation-plan.md`
  - `todos/{slug}/quality-checklist.md`
  - `todos/{slug}/state.json`

- Behavior contract:
  - Fails if `todos/{slug}` already exists.
  - Does not modify `todos/roadmap.md`.
  - `input.md` is optional and is not scaffolded by default.

## Allowed values

- Todo command: `telec todo create <slug> [--project-root PATH] [--after dep1,dep2]`.
- Sync command: `telec sync [--warn-only] [--validate-only] [--project-root PATH]`.
- Init command: `telec init`.

## Known caveats

- `telec sync` regenerates snippet indexes; do not hand-edit generated index files.
- `telec todo create` scaffolds files only; it does not insert roadmap entries or determine roadmap order.
- `telec init` should be rerun after hook/watcher artifact changes so runtime setup stays aligned.
