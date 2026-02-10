---
id: 'project/policy/bin-bootstrap-boundary'
type: 'policy'
scope: 'project'
description: 'Defines bin/ as bootstrap-only and clarifies where runtime and internal tooling belongs.'
---

# Bin Bootstrap Boundary — Policy

## Required reads

- @docs/project/policy/scripts-standalone-execution.md

## Rules

- `bin/` is bootstrap and platform-lifecycle surface only.
- Files in `bin/` must be limited to install, initialization, launch wrappers, and service control wiring.
- `bin/` shell scripts must not embed Python or other language heredocs. Call module entrypoints instead.
- Do not place routine runtime platform tooling in `bin/`.
- Do not place one-shot utilities, migration scripts, or AI scratch tooling in `bin/`.
- Runtime/public operator commands must live in `scripts/`.
- Internal engineering tooling must live in `tools/`.

## Rationale

- Keeping `bin/` small and purpose-bound prevents command-surface drift.
- Clear separation avoids AI agents dropping ad-hoc tools into lifecycle-critical locations.
- Distinct locations make maintenance and onboarding faster.

## Scope

- Applies to all contributors and AI agents modifying this repository.
- Applies to file placement decisions under `bin/`, `scripts/`, and `tools/`.

## Enforcement

- Review new files under `bin/` for bootstrap/lifecycle relevance before merge.
- Reject changes that add non-bootstrap tools to `bin/`.
- Use this placement map:
- `bin/`: install/init/service bootstrap and wrappers.
- `scripts/`: stable public runtime commands (symlinked to `~/.teleclaude/scripts`).
- `tools/`: internal dev/platform tooling (lint, formatting, checks, migrations, prep helpers).
- `teleclaude/entrypoints/`: Python module entrypoints invoked via `uv run -m ...`.

## Exceptions

- None. Any exception requires explicit human approval.
