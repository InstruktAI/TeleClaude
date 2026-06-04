---
description: 'How telec code commands resolve workspace scope across isolated worktrees, shared branches, and explicit file overrides.'
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

Three execution contexts drive file resolution:

1. **Worktree** — isolated by design. All dirty paths in the worktree belong to
   the task.
2. **Shared branch with session identity** — multiple agents may have
   uncommitted work. Scope to the current session's touched dirty files.
3. **Shared branch without session identity** — human or CI context. Callers use
   their command-specific full-run fallback.
4. **Explicit files** — caller passes file arguments directly. Skip workspace
   scoping.

`make lint` and `make test` defer to `telec code lint --all` and `telec code test --all` bare — they
do NOT rely on the scoping logic described here.

Pre-commit hooks are a separate path: they use `telec code lint --step <name>` with
`pass_filenames: true`. Pre-commit passes staged files directly. The scoping
logic in `LintRunner.run()` and `TestRunner.resolve_targets()` does not apply.

Tool invocation is separate from file scoping. In uv-managed Python projects,
`telec code lint` and `telec code test` resolve target files here, then invoke
Python project tools through the uv-managed entrypoints defined by the Python
tooling policy (`uv run pytest`, `uv run mypy`, `uv run pyright`, etc.).

The code owner for workspace-derived scope is
`teleclaude/quality/scope.py::resolve_workspace_scope_resolution()`. Callers may
own explicit file arguments, output rendering, staging, or fallback behavior,
but they do not branch on git worktree state directly.

## Inputs/Outputs

| Input              | Source                                         |
| ------------------ | ---------------------------------------------- |
| Execution context  | `resolve_workspace_scope_resolution()`         |
| Session identity   | `$TMPDIR/teleclaude_identity.json`             |
| Session transcript | Daemon transcript for the current session      |
| Dirty paths        | `git status --porcelain --untracked-files=all` |
| Project languages  | Detected from repo artifacts (`pyproject.toml`, `setup.py`, root Python files, `tsconfig.json`, TypeScript `package.json`, `Cargo.toml`) |
| Explicit file list | CLI arguments (`telec code lint <files...>`)   |

| Output                  | Description                                                               |
| ----------------------- | ------------------------------------------------------------------------- |
| `dirty_paths`           | Full dirty set from one porcelain parse, including operation kind         |
| `scoped_dirty_paths`    | Workspace-owned dirty paths, including deletions, safe for commit staging |
| `scoped_existing_paths` | Workspace-owned existing paths safe for format, lint, and test runners    |

## Invariants

1. **No stashing.** The scoping mechanism keeps files outside the agent's scope untouched, so there is never a need to stash anything aside.
2. **Worktrees are task-scoped.** A worktree is isolated — all dirty files
   belong to the task. Existing dirty files are the default format, lint, and
   test targets. Commit staging may also include deleted dirty paths.
3. **Shared branches are session-scoped.** On a shared branch, only files the
   current session touched and that are dirty are targeted. This prevents
   agents from linting, formatting, testing, or committing other agents'
   in-progress work.
4. **Explicit files override everything.** When the caller passes files as
   arguments, scoping is skipped entirely.
5. **Pre-commit is a separate path.** `telec code lint --step <name> [files...]`
   receives files from pre-commit's `pass_filenames`. The full-pipeline scoping
   logic does not apply.
6. **Scope failure is an error.** If workspace scope cannot be resolved and no
   explicit files are provided, the command exits non-zero with guidance:
   "pass files explicitly." It never silently falls back to a broader scope.
7. **No session identity on a shared branch means caller fallback.** Human and
   CI contexts have no session identity. `telec code lint` uses source
   directories, and `telec code test` uses configured test directories.
8. **Tool environment is uv-managed.** Scoping decides what to check; uv decides
   which Python project tool executable and dependency environment to use.

## Primary flows

### Worktree flow

```
telec code lint (no args, worktree detected)
  → resolve dirty paths once
  → use existing dirty paths as lint targets
```

```
telec code test (no args, worktree detected)
  → resolve dirty paths once
  → map existing dirty source files to companion tests
```

```
telec code commit (worktree detected)
  → resolve dirty paths once
  → git add dirty paths, including deletions
  → format/lint existing dirty paths
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
  → run pipeline against scoped files
```

### Shared branch flow (no session)

```
telec code lint (no args, not a worktree, no session identity)
  → resolve source dirs from language toolchain config as caller fallback
```

### Explicit files flow

```
telec code lint <files...>
  → skip scoping entirely
  → validate paths
  → run pipeline against provided files
```

### Pre-commit flow (unchanged)

```
telec code lint --step ruff_check <staged files from pre-commit>
  → run single step against provided files
  → no scoping logic involved
```

## Failure modes

### Workspace scope unavailable

Git status, session identity, or transcript collection fails while resolving
workspace scope.

**Response:** Exit non-zero. Error message includes actionable guidance:
`Workspace scope unavailable. Pass files explicitly: telec code lint <files...>`

The agent reads this and retries with explicit file arguments. No silent
fallback.

### No session identity on shared branch

No `teleclaude_identity.json` present. This is a human or CI context.

**Response:** Caller fallback. For lint this is source directories. For tests
this is configured test directories. Expected behavior for manual runs.

### No recognised language artifacts

No Python, TypeScript, or Rust artifact is found at the project root or in a
recognised frontend directory.

**Response:** Quality tools detect no languages and skip all pipelines. Use `telec code lint/test/format` after adding the appropriate language artifact.
