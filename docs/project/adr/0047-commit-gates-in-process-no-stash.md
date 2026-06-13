---
date: '2026-06-11'
description: 'telec code commit runs format then lint in-process before git commit --no-verify; the pre-commit framework is retired; .git/hooks/pre-commit is a thin fail-closed partial-staging guard.'
number: '47'
visibility: 'public'
---

# ADR-0047: Commit Gates Run In-Process; Pre-Commit Framework Retired — ADR

## Context

`telec code commit` previously committed through the pre-commit framework, which used a stash/restore cycle to align the hook's working tree with the staged snapshot. On shared-main multi-agent branches that stash transiently reverts other agents' uncommitted files — a concurrency hazard. An existing in-process partial-staging guard already showed that in-process quality enforcement works without a stash.

## Decision

`telec code commit` runs format, then lint, in-process against the commit pathspec (filtered to existing files) before committing with `--no-verify`. Format runs before lint so lint checks post-format bytes; deletion-only commits skip both; the commit proceeds only if all in-process gates pass.

The pre-commit framework is retired — its config becomes an empty stub, and the installed `.git/hooks/pre-commit` is a thin, fail-closed, telec-owned partial-staging guard, a backstop for raw `git commit` invocations.

## Consequences

- No framework stash — files outside the commit pathspec are never transiently modified, removing the multi-agent hazard.
- Gates check exactly what is committed; there is no staging-vs-working-tree mismatch.
- Deletion-only commits skip format and lint.
- `make install` deploys the thin hook; generated projects receive it via the skeleton deployer.
