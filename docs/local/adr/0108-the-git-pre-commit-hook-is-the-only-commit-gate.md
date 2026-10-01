---
date: '2026-10-01'
description: 'The git pre-commit hook runs the commit gate for every route into a commit; telec code commit formats and scopes, then lets git run the hook. Lint grades the commit as staged against the rest of each home as committed, so no stash is needed.'
number: '108'
visibility: 'public'
---

# ADR-0108: The Git Pre-Commit Hook Is the Only Commit Gate — ADR

## Context

ADR-0047 moved format and lint out of the pre-commit framework and into
`telec code commit`, which then commits with `--no-verify`. The installed
`.git/hooks/pre-commit` was reduced to a partial-staging guard, and exits
without checking anything in a context that carries no `code` capability. The
reason was real: the framework's stash and restore briefly reverted other
agents' uncommitted files on shared `main`.

The cost was the guarantee itself. Only one route into a commit was gated. A
raw `git commit` from a terminal, an automated commit, or any tool that does
not go through `telec code commit` records content no check ever saw. Invalid
documentation reached the global home's committed history this way.
Publication then re-validated committed state and stalled on it, which made a
second gate downstream of the first.

The stash was never what made the hook unsafe. Once the partial-staging guard
refuses a staged path that also carries unstaged changes, every staged file on
disk is exactly what will be committed. When `git commit -- <pathspec>` runs,
git hands the hook a temporary index holding exactly the commit's file set. A
check can read that index directly, without moving anyone's working files.

## Decision

The git `pre-commit` hook is the commit gate for every route into a commit.
`telec code pre-commit`, which the hook runs, applies the partial-staging guard
and then lints the staged file set. It applies the same check selection the
acting tier carries, and checks formatting rather than rewriting files.
Validators that resolve across files grade the staged files against the rest
of each owning home as committed, not against other sessions' uncommitted
files. The hook runs for every context that carries a gate, with or without
`code`.

`telec code commit` keeps scope resolution and staging. It formats its own
pathspec before staging, and then lets git run the hook. No commit route passes
`--no-verify`.

Committed state is the source of truth. Nothing downstream of the commit
re-validates it.

## Consequences

- A raw `git commit` and `telec code commit` of the same file set get the same
  verdict, with the same findings.
- No stash and no working-tree rewrite outside the commit's own pathspec. The
  hazard ADR-0047 removed stays removed.
- One session's uncommitted invalid file in a shared home no longer blocks
  another session's unrelated commit.
- The hook rejects an unformatted file instead of fixing it. A raw `git commit`
  of unformatted content fails and names the format command.
- Every commit pays for lint, including automated commits that previously
  bypassed it. A slow check is now on every commit route.
- Downstream consumers, publication included, trust committed state and derive
  from it.

## Alternatives Considered

- **Keep the in-process gate and add lint to the thin hook as well.** Rejected:
  two implementations of one gate drift, and a commit through `telec code commit`
  would be linted twice.
- **Reinstate the pre-commit framework.** Rejected: its stash and restore is the
  hazard ADR-0047 removed.
- **Format inside the hook and re-stage.** Rejected: rewriting files while git
  holds a temporary index for a pathspec commit lets the working tree, the
  temporary index, and the real index diverge.
