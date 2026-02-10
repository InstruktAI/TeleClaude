---
id: 'project/policy/scripts-standalone-execution'
type: 'policy'
scope: 'project'
description: 'Execution contract for scripts/: portable invocation, uv metadata, and robust preflight validation.'
---

# Scripts Standalone Execution — Policy

## Required reads

- @docs/project/design/architecture/jobs-runner.md
- @docs/global/general/spec/tools/telec-cli.md

## Rules

- `scripts/` is a public runtime surface. Only durable, operator-facing commands belong there.
- Every runnable Python file under `scripts/` must use a `uv` shebang: `#!/usr/bin/env -S uv run` (or `--quiet`).
- Every runnable Python file under `scripts/` must include a PEP 723 metadata block (`# /// script`) with explicit third-party dependencies.
- Scripts must work from any working directory. They must not assume the caller is at repo root.
- Repository-relative operations must resolve from script location or an explicit `--project-root` argument.
- Scripts must validate required inputs and environment explicitly, then exit with actionable error messages.
- Missing prerequisites must be reported by validation logic; avoid opaque import/path crashes for expected operator mistakes.
- Shell scripts in `scripts/` must follow the same cwd-independence rule and accept explicit path overrides when they touch repo files.
- `telec sync` behavior is the model: explicit project root handling, deterministic validation, and stable execution across invocation contexts.
- One-shot migration utilities, personal tooling, temporary debugging scripts, and AI scratch helpers must not be created in `scripts/`.
- Internal-only utilities must live outside the symlinked runtime surface (for example under `tools/` or `devtools/`).

## Rationale

- `scripts/` is deployed via `~/.teleclaude/scripts`, so callers often execute outside this repository.
- Portable scripts reduce operational drift across local, remote, and agent-driven usage.
- PEP 723 metadata makes dependency resolution deterministic and self-contained.
- Preflight validation prevents brittle failures and lowers troubleshooting cost.

## Scope

- Applies to all runnable files in `scripts/` and `scripts/helpers/`.
- Applies to both human-invoked and agent-invoked script execution paths.

## Enforcement

- New or changed scripts must pass a portability review:
- Confirm `uv` shebang and PEP 723 metadata for runnable Python scripts.
- Confirm invocation works from non-repo cwd (`/tmp` smoke run).
- Confirm repo-dependent scripts expose explicit root resolution (`__file__` anchor and/or `--project-root`).
- Confirm validation errors are explicit and actionable.
- Confirm script classification: if it is not a stable public command, it must not be under `scripts/`.

## Exceptions

- Non-runnable module files (for example `scripts/__init__.py`) are exempt from shebang/PEP 723 requirements.
- Repo-bound daemon tooling may import `teleclaude` modules directly, but still must remain cwd-independent and declare third-party dependencies in PEP 723 metadata.
