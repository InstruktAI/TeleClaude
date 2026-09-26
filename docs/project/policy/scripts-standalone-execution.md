---
description: 'Execution contract for scripts/: portable invocation, uv metadata, and robust preflight validation.'
visibility: 'public'
---

# Scripts Standalone Execution — Policy

## Required reads

- @docs/project/design/architecture/jobs-runner.md
- @~/.teleclaude/docs/general/spec/tools/telec-cli.md

## Rules

- `scripts/` is a public runtime surface. Only durable, operator-facing commands belong there.
- Every runnable Python file under `scripts/` must use a `uv` shebang: `#!/usr/bin/env -S uv run` (or `--quiet`).
- Every runnable Python file under `scripts/` must include a PEP 723 metadata block (`# /// script`) with explicit third-party dependencies.
- Scripts must work from any working directory. They must not assume the caller is at repo root.
- Repository-relative operations must resolve from script location or an explicit `--project-root` argument.
- Scripts must validate required inputs and environment explicitly, then exit with actionable error messages.
- Missing prerequisites must be reported by validation logic; avoid opaque import/path crashes for expected operator mistakes.
- Shell scripts in `scripts/` must follow the same cwd-independence rule and accept explicit path overrides when they touch repo files.
- The publication pipeline's behavior is the model: explicit project root handling, deterministic validation, and stable execution across invocation contexts.
- One-shot migration utilities, personal tooling, temporary debugging scripts, and AI scratch helpers must not be created in `scripts/`.
- Internal-only utilities must live outside the symlinked runtime surface (for example under `tools/` or `devtools/`).
<!-- planned-change:align-scripts-runtime-boundary-delivery -->
- Scripts must not import the `teleclaude` package at module level. Inline any needed types, constants, or utilities directly into the script. Lazy `teleclaude` imports are acceptable only inside a `try/except` that handles the package's absence gracefully.
- Scripts must not manipulate `sys.path` (no `sys.path.insert`, no `parents[N]` walks) to locate the `teleclaude` package — the symlinked runtime surface makes such tricks break when the script runs from `~/.teleclaude/scripts` rather than the repo checkout.
- Importing between scripts within `scripts/` is acceptable (they share the symlinked location); importing from `teleclaude.*` is not.
<!-- change:align-scripts-runtime-boundary-delivery -->
- Standalone execution never creates a second implementation owner. Each public capability names one canonical module; every in-process consumer imports that owner instead of maintaining a package-side copy.
- A portable public script owns its complete capability under `scripts/` and carries its PEP 723 dependencies there. Shared first-party types, constants, parsing, and decisions stay in that script and are imported by consumers; they are never copied into `teleclaude/`.
- A repo-bound process entrypoint may import its canonical `teleclaude` module directly when the package owns the capability. The entrypoint contains only argument, startup, and presentation adaptation; domain and workflow behavior stay in the package owner.
- Scripts never manipulate `sys.path` to locate first-party code. A repo-bound entrypoint invoked through its `uv` shebang may transfer to its source checkout's installed project interpreter before importing first-party code, preserving its arguments and the public script path. It fails with an actionable diagnostic when that runtime is absent or cannot supply the owner package.
- Importing between canonical modules under `scripts/` is permitted. A cross-boundary import never grants permission to duplicate the imported owner's knowledge.
<!-- /planned-change:align-scripts-runtime-boundary-delivery -->
- Runnable scripts must have the executable bit set in the repository.

## Rationale

- `scripts/` is deployed via a `~/.teleclaude/scripts` symlink created by `make install`; the source file IS the deployed file (no copy step), so edits take effect immediately and callers often execute outside this repository.
- Portable scripts reduce operational drift across local, remote, and agent-driven usage.
<!-- planned-change:align-scripts-runtime-boundary-delivery -->
- PEP 723 metadata makes dependency resolution deterministic and self-contained.
<!-- change:align-scripts-runtime-boundary-delivery -->
- PEP 723 metadata makes portable scripts' third-party dependencies deterministic. A repo-bound entrypoint uses its installed project interpreter for first-party packages because an inline-metadata `uv` run is isolated from the project.
<!-- /planned-change:align-scripts-runtime-boundary-delivery -->
- Preflight validation prevents brittle failures and lowers troubleshooting cost.
<!-- planned:align-scripts-runtime-boundary-delivery -->
- Standalone is an invocation property, not an ownership model. Copying a package implementation into a public script creates two authorities that drift; one canonical owner preserves both portability and internal reuse.
- Keeping internal tooling, migrations, and experiments outside the whole-tree symlink makes the deployed surface tell the truth about what operators and agents may rely on.
<!-- /planned:align-scripts-runtime-boundary-delivery -->

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
<!-- planned:align-scripts-runtime-boundary-delivery -->
- Confirm the command names its canonical implementation owner and that no parallel implementation of the same capability exists in another source root.
- A broad directory-level lint exemption for `scripts/**` is rejected; a surviving exception is the narrow declaration already owned by the applicable configuration.
<!-- /planned:align-scripts-runtime-boundary-delivery -->

## Exceptions

- Non-runnable module files (for example `scripts/__init__.py`) are exempt from shebang/PEP 723 requirements.
- Repo-bound daemon tooling may import `teleclaude` modules directly, but still must remain cwd-independent and declare third-party dependencies in PEP 723 metadata.
