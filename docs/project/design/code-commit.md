---
id: project/design/code-commit
type: design
domain: software-development
scope: project
description: Design of telec code commit — the explicit staging, formatting, linting, and commit command that replaces the git wrapper.
---

# Code Commit — Design

## Purpose

`telec code commit` is the canonical commit interface for agent and human sessions.
It replaces the former git wrapper (`~/.teleclaude/bin/git`) with an explicit command
that resolves session-scoped files, stages them, runs formatting and linting, then
invokes `git commit`.

The driving constraint: git ignores index changes made inside pre-commit hooks when
the commit starts with an empty index. The hook-based staging approach silently dropped
files. Moving staging before `git commit` solves this at the root.

## Inputs/Outputs

**Inputs:**

- `--no-scope` — skip session-scope resolution (commit whatever is already staged)
- `--no-lint` — skip lint step
- `--no-format` — skip format step
- `-- <git-commit-args>` — everything after `--` passes through to `git commit`

**Outputs:**

- Staged, formatted, linted commit — or failure with clear diagnostics
- Exit code from `git commit` propagated to caller

## Invariants

1. **Staging before commit.** Session-scoped files are staged via `git add` before
   `git commit` is invoked. The pre-commit hook never stages files.
2. **Format then lint.** Formatting runs first, modified files are restaged, then lint
   runs against the formatted versions. This prevents format-lint oscillation.
3. **Session scoping.** `tools/session_scope.py --mode lint` determines which files
   belong to the current session. In worktrees, the fallback is `git status --porcelain`.
   Outside agent sessions, scoping is skipped gracefully — whatever is already staged
   is committed.
4. **Partial staging blocked.** Files that are both staged and unstaged are rejected
   to prevent pre-commit stash corruption.
5. **Pre-commit hook is lint-only.** The `.git/hooks/pre-commit` hook runs
   `.pre-commit-config.yaml` checks (commitizen, ruff, pyright, docs validation)
   against already-staged files. It does not stage, format-restage, or scope.

## Primary flows

### Agent commit (tmux or headless)

```
telec code commit -- -m "feat(scope): subject"
  → session_scope.py resolves touched files
  → git add -- <files>
  → FormatRunner.run(files=staged)
  → restage formatter-modified files
  → LintRunner.run(files=staged)
  → git commit -m "feat(scope): subject"
    → pre-commit hook runs .pre-commit-config.yaml checks
    → commit created
```

### Integration commit

```
telec code commit --no-scope -- -m "feat(slug): deliver slug"
  → skip session scope (integrator staged manually)
  → FormatRunner + LintRunner on staged files
  → git commit
```

### Human commit

Humans can use `telec code commit` or raw `git commit` (with manual staging).
The pre-commit hook still runs quality checks either way.

## Failure modes

**Empty scope.** Session has no touched files and nothing is manually staged.
`telec code commit` prints "Nothing staged for commit." and exits 1.

**Partial staging.** Files appear in both staged and unstaged state. Blocked with
diagnostic listing the affected files. Resolution: `git add -p` to complete staging
or `--no-scope` to skip session resolution.

**Lint failure.** `LintRunner.run()` raises `SystemExit` on any check failure.
The commit is aborted. Files remain staged for the agent to fix and retry.

**Format modification.** Formatter changes files after staging. The command detects
this and restages before linting. No manual intervention needed.

## See Also

- docs/global/software-development/design/session-file-scoping.md
- docs/global/software-development/policy/version-control-safety.md
