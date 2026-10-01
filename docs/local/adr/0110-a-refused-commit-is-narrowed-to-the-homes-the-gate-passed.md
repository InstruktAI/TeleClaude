---
date: '2026-10-01'
description: "When the commit gate refuses a sealed commit, telec code commit reacts to the gate's own per-home verdict: it commits again with only the owning homes whose checks passed, once, and leaves the refused homes uncommitted for their authors. It never validates on its own."
number: '110'
visibility: 'public'
---

# ADR-0110: A Refused Commit Is Narrowed to the Homes the Gate Passed — ADR

## Context

A repository can host several teleclaude homes: the global home hosts person
and company homes, and a monorepo hosts several project homes. Under ADR-0108
the git pre-commit hook is the only commit gate. It judges the staged file set
as a whole and selects checks by each staged path's owning home. One invalid
home therefore refuses the entire commit, valid changes to every other home
included. In a shared home, the author of the valid change is held up by
material that is not theirs to fix.

A pre-commit hook can only accept or reject the commit it is shown; it cannot
remove part of it. Any partial outcome has to come from whatever builds the
commit's pathspec.

Validity of documentation and agent artifacts is home-relative. References,
identities and collisions resolve across a home's files, so a subset of one
home's changes can be invalid as a whole even when each file reads correctly on
its own.

## Decision

When the gate refuses a `telec code commit`, the command reacts to the gate's
own verdict for that attempt. The verdict states, for each owning home of the
staged paths, whether that home's checks passed. When every finding belongs to
an owning home and at least one home in the commit passed, the command commits
again with only the passing homes' paths. That commit passes through the gate
like any other. The command retries once, reports every dropped home with its
findings, and exits non-zero. Dropped files stay uncommitted for their authors.

The unit dropped is the owning home, never the single file. A refusal the gate
cannot attribute to owning homes, a merge commit, and a raw `git commit` are
not narrowed.

## Consequences

- One invalid home no longer holds valid work in the other homes of the same
  repository hostage.
- Validation still happens only in the gate. The commit side reads a verdict and
  shrinks a pathspec; it holds no check of its own.
- Nothing invalid enters history. Every path that lands passed the gate in the
  commit that recorded it.
- A sealed commit can now land less than its author asked for. The command
  exits non-zero and names what was left out, so an author or a calling tool
  that reads only the exit status still sees that the request was not met in
  full.
- A narrowed commit costs a second gate run.
- The hook and the sealed commit share a verdict format, which both must keep
  in step. A hook that does not provide the verdict leaves the refusal whole,
  which is the behavior before this decision.
- A raw `git commit` still gets a whole refusal. Its author narrows by hand.

## Alternatives Considered

- **Validate in `telec code commit` before calling git, and commit only the
  valid homes.** Rejected: it is a second validator beside the hook. The two
  would drift, and the commit would be graded twice.
- **Drop the single files that carry findings.** Rejected: home-relative
  validity means a finding in one file can be caused by a change to another
  file of the same home. Dropping only the named file keeps the cause in the
  retry, which the gate then refuses again, or lands half of a change its
  author meant to land as one.
- **Keep the whole refusal.** Rejected: one author's invalid home blocks every
  other author's valid work in a shared repository until it is fixed.
- **Retry until the gate passes.** Rejected: a second refusal means the homes
  are not independent in this commit, for example a nested home that relies on
  a dropped change in the global home. Further narrowing guesses at a
  dependency the author has to resolve.
