---
adr_status: 'accepted'
date: '2026-06-11'
description: 'telec code commit runs format then lint in-process before git commit --no-verify; the pre-commit framework is retired; .git/hooks/pre-commit is a thin fail-closed partial-staging guard.'
number: '36'
visibility: 'public'
---

# ADR-0036: Commit Gates Run In-Process; Pre-Commit Framework Retired — ADR

## Context

`telec code commit` previously committed via `git commit` with the pre-commit
framework installed at `.git/hooks/pre-commit`. The framework used a stash/restore
cycle to ensure the hook's working tree matched the staged snapshot. On shared-main
multi-agent branches this stash transiently reverts other agents' uncommitted files,
creating a concurrency hazard. The existing in-process partial-staging guard in
`_commit_under_lock` already demonstrated that in-process quality enforcement is
viable without a stash.

## Decision

`telec code commit` runs format then lint in-process against `quality_paths` (the
commit pathspec filtered to existing files) before `git commit --no-verify`:

1. Commitizen message format is validated in-process.
2. `quality_paths = [p for p in pathspec if (project_root / p).exists()]` —
   deletion-only commits (empty `quality_paths`) skip format and lint.
3. `handle_format(quality_paths)` runs first (format before lint so lint checks
   post-format bytes).
4. `handle_lint(quality_paths)` runs in filesystem-read mode so home-path violations
   in modified-tracked files are caught before the `--no-verify` commit.
5. `git commit --no-verify` only if all in-process gates pass.

The pre-commit framework is retired. `.pre-commit-config.yaml` becomes a `repos: []`
stub. `.git/hooks/pre-commit` is a thin fail-closed telec-owned partial-staging
guard: NUL-safe Python, exits nonzero if `git status` fails (fail-closed).

## Consequences

- No framework stash — files outside the commit pathspec are never transiently
  modified.
- Gates check exactly what is committed — no staging-vs-working-tree mismatch.
- Format-before-lint order — lint always checks post-format bytes.
- Deletion-only commits skip format and lint.
- `check-cli-help` and `check-raw-sql` migrate to the guardrails lane.
- `make install` deploys the thin hook; generated projects receive the hook source
  via the updated skeleton deployer.
