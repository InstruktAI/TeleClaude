---
description: 'How telec code commands resolve workspace scope and hand it to the project''s own make targets across isolated worktrees, shared branches, and explicit file overrides.'
domain: 'software-development'
id: 'software-development/design/workspace-scoping'
scope: 'global'
type: 'design'
visibility: 'public'
---

# Workspace Scoping — Design

## Purpose

`telec code` commands run from isolated worktrees, shared branches, human shells,
and CI. Workspace scoping decides which paths belong to the current operation
without stashing and without touching another agent's in-progress files.

`telec code` is a thin scoping shim. It resolves which files the current
operation owns, then delegates execution to the project's own `make` targets —
it embeds no toolchain and runs no lint/test/format tools itself. The project's
`Makefile` runs the real suite (native tools plus any repo-local policy scripts)
with zero TeleClaude dependency. Scoping is the only value `telec code` adds on
top of `make`.

Three execution contexts drive file resolution:

1. **Worktree** — isolated by design. All dirty paths in the worktree belong to
   the task.
2. **Shared branch with session identity** — multiple agents may have
   uncommitted work. Scope to the current session's touched dirty files.
3. **Shared branch without session identity** — human or CI context. Callers run
   the full suite (no file list).
4. **Explicit files** — caller passes file arguments directly. Skip workspace
   scoping.

`make lint` and `make test` are the project's own entrypoints; they run native
tools directly and do NOT call back into `telec code`. The delegation is
one-directional: `telec code lint` resolves scope and invokes `make lint`,
passing the scoped file list as a **NUL-delimited `FILES_FROM` temp file** (the
list of paths never travels on the `make` command line, in `$@`/`$*`, or as a
make goal). A `make lint` with no `FILES_FROM` runs the whole suite. There is no
`telec code → make → telec code` cycle.

Pre-commit hooks are a separate path: a wrapper writes the staged files
NUL-delimited to a temp file and runs `make lint FILES_FROM=<tmpfile>`
(pre-commit appends filenames as argv; the wrapper repackages them into the
`FILES_FROM` file rather than a shell-split variable). Pre-commit auto-stashes
unstaged changes, so the working tree it lints equals the staged snapshot. The
full-pipeline scoping logic in `telec code lint` does not apply on this path.

Tool invocation is separate from file scoping. `telec code` decides which files
are in play and serializes them into the `FILES_FROM` file; the `Makefile`
recipes own how each tool runs (e.g. `uv run pyright`, `uv run mypy`, `ruff`,
`jscpd`, `cargo`, and the repo-local `python tools/lint/*.py` policy scripts),
consuming the list NUL-safely. In uv-managed Python projects the make recipes
invoke project tools through the uv-managed entrypoints defined by the Python
tooling policy.

The code owner for workspace-derived scope is
`teleclaude/quality/scope.py::resolve_workspace_scope_resolution()`. Callers may
own explicit file arguments, output rendering, staging, or fallback behavior,
but they do not branch on git worktree state directly. Each `telec code` verb
then serializes the resolved scope into the `FILES_FROM` temp file and invokes
`make`.

## Inputs/Outputs

| Input              | Source                                                                                                                                   |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Execution context  | `resolve_workspace_scope_resolution()`                                                                                                   |
| Session identity   | `$TMPDIR/teleclaude_identity.json`                                                                                                       |
| Session transcript | Daemon transcript for the current session                                                                                                |
| Dirty paths        | `git status --porcelain --untracked-files=all`                                                                                           |
| Project languages  | Detected from repo artifacts (`pyproject.toml`, `setup.py`, root Python files, `tsconfig.json`, TypeScript `package.json`, `Cargo.toml`) |
| Explicit file list | CLI arguments (`telec code lint <files...>`)                                                                                             |

| Output                  | Description                                                                                |
| ----------------------- | ------------------------------------------------------------------------------------------ |
| `dirty_paths`           | Full dirty set from one porcelain parse, including operation kind                          |
| `scoped_dirty_paths`    | Workspace-owned dirty paths, including deletions, safe for commit staging                  |
| `scoped_existing_paths` | Workspace-owned existing paths, serialized into the `FILES_FROM` file / staged for commit  |

## Invariants

1. **No stashing.** The scoping mechanism keeps files outside the agent's scope untouched, so there is never a need to stash anything aside.
2. **Worktrees are task-scoped.** A worktree is isolated — all dirty files
   belong to the task. Existing dirty files become the `FILES_FROM` list for
   lint and the commit-staging set. Commit staging may also include deleted
   dirty paths.
3. **Shared branches are session-scoped.** On a shared branch, only files the
   current session touched and that are dirty enter the `FILES_FROM` list. This
   prevents agents from linting or committing other agents' in-progress work.
4. **Explicit files override everything.** When the caller passes files as
   arguments, scoping is skipped and those files become the `FILES_FROM` list
   directly.
5. **Pre-commit is a separate path.** A wrapper serializes pre-commit's staged
   file list into the `FILES_FROM` temp file; the full-pipeline scoping logic
   does not apply.
6. **Scope failure is an error.** If workspace scope cannot be resolved and no
   explicit files are provided, the command exits non-zero with guidance:
   "pass files explicitly." It never silently falls back to a broader scope.
7. **No session identity on a shared branch means full run.** Human and CI
   contexts have no session identity; `telec code lint` runs `make lint` with no
   `FILES_FROM` (the whole suite).
8. **Tool environment is owned by make.** Scoping decides what to check; the
   project's `make` recipes decide which tool executables and dependency
   environment to use. `telec code` invokes no tool of its own.
9. **`make test` is never file-scoped.** The spec-anchored model has no 1:1
   source→test map, so `telec code test` delegates to `make test` with no scope.
10. **File-scoped vs full-run behavior lives behind make.** On file-scoped runs
    (worktree, shared branch with session identity, explicit files) `FILES_FROM`
    points at a NUL-delimited temp file and the make recipes scope each tool to
    those paths (native tools via `xargs -0`, policy scripts via
    `--files-from`). On full runs (`--all`, shared branch without session
    identity, CI) no `FILES_FROM` is set and the recipes run repo-wide. Because
    paths travel in a NUL-delimited file rather than on a command line, a
    filename containing spaces or shell metacharacters cannot word-split or
    inject a make goal. Repo-wide doc-index cross-reference validation is not
    part of `make lint` — it runs in CI — so an agent's scoped lint never fails
    on another agent's in-flight docs.

## Primary flows

### Worktree flow

```
telec code lint (no args, worktree detected)
  → resolve dirty paths once
  → write existing dirty paths NUL-delimited to a FILES_FROM temp file
  → invoke make lint FILES_FROM=<tmpfile>
```

```
telec code test (no args)
  → make test (unscoped — no 1:1 source→test map)
```

```
telec code commit (worktree detected)
  → resolve dirty paths once
  → git add dirty paths, including deletions
  → pathspec-scoped commit (pre-commit runs make lint/format on the staged set)
```

```
telec code changed (worktree detected)
  → resolve dirty paths once
  → print dirty paths, including deletions
```

### Shared branch flow (session available)

```
telec code lint (no args, not a worktree, session identity present)
  → resolve dirty paths once
  → intersect dirty files with session-touched files from transcript
  → validate paths (no traversal, no absolute paths outside project)
  → write scoped paths NUL-delimited to a FILES_FROM temp file
  → invoke make lint FILES_FROM=<tmpfile>
```

### Shared branch flow (no session)

```
telec code lint (no args, not a worktree, no session identity)
  → invoke make lint (no FILES_FROM — full suite)
```

### Explicit files flow

```
telec code lint <files...>
  → skip scoping entirely
  → validate paths
  → write provided files NUL-delimited to a FILES_FROM temp file
  → invoke make lint FILES_FROM=<tmpfile>
```

### Pre-commit flow

```
pre-commit (staged files as argv)
  → wrapper writes staged files NUL-delimited to a FILES_FROM temp file
  → make lint FILES_FROM=<tmpfile>
  → make recipes scope each tool to those paths (xargs -0 / --files-from)
  → no telec code scoping logic involved
```

### Full-run flow

```
telec code lint --all   (or make lint with no FILES_FROM, CI, no-session shared branch)
  → make lint (no FILES_FROM) → every tool runs repo-wide
  → doc-index cross-reference validation runs in CI, not in make lint
```

## Failure modes

### Workspace scope unavailable

Git status, session identity, or transcript collection fails while resolving
workspace scope.

**Response:** Exit non-zero. Error message includes actionable guidance:
`Workspace scope unavailable. Pass files explicitly: telec code lint <files...>`

The agent reads this and retries with explicit file arguments. No silent
fallback to a broader scope.

### No session identity on shared branch

No `teleclaude_identity.json` present. This is a human or CI context.

**Response:** Run `make lint` with no `FILES_FROM` — the full suite. Expected
behavior for manual runs.

### No recognised language artifacts / missing make target

`make lint` has nothing to run, or the project has no `Makefile` target to
delegate to.

**Response:** `make` reports the missing target; `telec code <verb>` surfaces it
and points at the project-toolchain assessment to wire the target up. Use
`telec code lint/test/format` after the `Makefile` exposes the target.
