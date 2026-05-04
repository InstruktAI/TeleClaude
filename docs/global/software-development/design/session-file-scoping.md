---
id: 'software-development/design/session-file-scoping'
type: 'design'
domain: 'software-development'
scope: 'global'
description: 'How telec code lint and telec code test resolve file targets based on execution context — worktree isolation, session scoping on shared branches, and explicit file override.'
---

# Session File Scoping — Design

## Purpose

`telec code lint` and `telec code test` run from any project directory. They determine which
files to operate on without stashing, without touching other agents' files, and
without manual configuration.

Three execution contexts drive file resolution:

1. **Worktree** — isolated by design. Run against all source directories.
2. **Shared branch** — multiple agents may have uncommitted work. Scope to the
   current session's touched files via transcript.
3. **Explicit files** — caller passes file arguments directly. Skip all scoping.

`make lint` and `make test` defer to `telec code lint --all` and `telec code test --all` bare — they
do NOT rely on the scoping logic described here.

Pre-commit hooks are a separate path: they use `telec code lint --step <name>` with
`pass_filenames: true`. Pre-commit passes staged files directly. The scoping
logic in `LintRunner.run()` and `TestRunner.resolve_targets()` does not apply.

Tool invocation is separate from file scoping. In uv-managed Python projects,
`telec code lint` and `telec code test` resolve target files here, then invoke
Python project tools through the uv-managed entrypoints defined by the Python
tooling policy (`uv run pytest`, `uv run mypy`, `uv run pyright`, etc.).

## Inputs/Outputs

| Input              | Source                                         |
| ------------------ | ---------------------------------------------- |
| Execution context  | `is_worktree()` detection via git plumbing     |
| Session identity   | `$TMPDIR/teleclaude_identity.json`             |
| Session transcript | Daemon transcript for the current session      |
| Project languages  | `teleclaude.yml` `language`/`languages` config |
| Explicit file list | CLI arguments (`telec code lint <files...>`)   |

| Output       | Description                                                 |
| ------------ | ----------------------------------------------------------- |
| File targets | Files or directories passed to lint pipeline or test runner |

## Invariants

1. **No stashing.** The scoping mechanism exists to eliminate the need for
   `git stash`. Files outside the agent's scope are never touched.
2. **Worktrees are repo-wide.** A worktree is isolated — all files belong to
   the task. Source directories from the language toolchain are the targets.
3. **Shared branches are session-scoped.** On a shared branch, only files the
   current session touched (via transcript) are targeted. This prevents agents
   from linting, formatting, or testing other agents' in-progress work.
4. **Explicit files override everything.** When the caller passes files as
   arguments, scoping is skipped entirely.
5. **Pre-commit is a separate path.** `telec code lint --step <name> [files...]`
   receives files from pre-commit's `pass_filenames`. The full-pipeline scoping
   logic does not apply.
6. **Scope failure with a session identity is an error.** If session scope
   cannot be resolved and no explicit files are provided, the command exits
   non-zero with guidance: "pass files explicitly." It never silently falls
   back to repo-wide execution.
7. **No session identity means repo-wide.** Human and CI contexts have no
   session identity. They expect full verification against source directories.
8. **Tool environment is uv-managed.** Scoping decides what to check; uv decides
   which Python project tool executable and dependency environment to use.

## Primary flows

### Worktree flow

```
telec code lint (no args, worktree detected)
  → resolve source dirs from language toolchain config
  → run pipeline against all source dirs
```

### Shared branch flow (session available)

```
telec code lint (no args, not a worktree, session identity present)
  → resolve session-touched files from transcript
  → validate paths (no traversal, no absolute paths outside project)
  → run pipeline against scoped files
```

### Shared branch flow (no session)

```
telec code lint (no args, not a worktree, no session identity)
  → resolve source dirs from language toolchain config
  → run pipeline against all source dirs
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

### Transcript unavailable on shared branch

Session identity exists but transcript cannot provide touched files (e.g., agent
operated via git commands only, transcript not yet flushed).

**Response:** Exit non-zero. Error message includes actionable guidance:
`Session scope unavailable. Pass files explicitly: telec code lint <files...>`

The agent reads this and retries with explicit file arguments. No silent fallback.

### No session identity on shared branch

No `teleclaude_identity.json` present. This is a human or CI context.

**Response:** Source directories (repo-wide). Expected behavior for manual runs.

### Missing language config

`teleclaude.yml` has no `language` or `languages` field.

**Response:** Project root used as the single target directory.
