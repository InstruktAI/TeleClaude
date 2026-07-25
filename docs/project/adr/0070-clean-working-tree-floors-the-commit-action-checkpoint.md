---
visibility: public
number: 0070
date: 2026-07-25
description: The agent_stop commit-action checkpoint additionally suppresses on a definitively clean working tree; a positively-read empty git status is a guaranteed floor over ADR-0037's timeline-evidence suppression, refining but not reversing it.
---

# Clean Working Tree Floors the Commit-Action Checkpoint — ADR

## Context

ADR-0037 decided that suppression of the agent_stop commit action derives from
commit evidence in the turn timeline, and that git is consulted only as the
category oracle, never as the arbiter of what is in-scope or done. That held while
a session's own timeline was the complete record of what it committed.

It is not complete in a shared task worktree. Multiple sessions — builder,
reviewer, fixer — operate in one per-slug worktree. When a peer session commits a
file, that commit is absent from this session's turn timeline, so timeline
evidence cannot account for it. Meanwhile the commit action's input file set is
derived from an anchor-relative diff that still lists the now-committed path.
Observed live: a reviewer session — which by role commits nothing — was told
"commit your changes" on three consecutive turns with a provably clean worktree
(`git status --porcelain` empty), and could only escape via the turn-scoped clear
flag. The escape hatch, meant to be a last resort, became routine, eroding the
very signal ADR-0037's turn-scoped hatch exists to protect.

The gap: timeline evidence is a per-session proxy for a fact that is global to the
working tree — whether anything is uncommitted at all.

## Decision

Add a guaranteed clean-tree floor to the commit-action decision, refining
ADR-0037's timeline-evidence suppression:

- When the working-tree status (`git status --porcelain --untracked-files=all`) is
  read successfully and is empty, the tree is definitively clean and the commit
  action is not owed — suppressed regardless of the attributed file set.
- When the status is non-empty, or cannot be read, ADR-0037's existing decision
  applies unchanged: timeline-evidence suppression governs the dirty case, and a
  failed read falls through to the existing visible-fallback behavior rather than a
  silent all-clear.

This narrows, and does not reverse, ADR-0037. Git remains the category oracle for
the maintenance ledger, and committed code is still sourced into the ledger so
maintenance actions survive a HEAD move. The floor consults git state only as a
clean/dirty necessary condition for the commit action — nothing uncommitted means
nothing to commit — never to arbitrate which files belong to which session.

## Consequences

- A commit action can no longer fire on a provably clean worktree, closing the
  false-nag that pushed sessions to the escape hatch.
- The floor is a pure suppression: it can only withhold a commit action on a
  positively-read empty tree, never add one, and never touches any other action,
  category, maintenance obligation, or the post-commit review gate.
- Timeline-evidence suppression is retained for the dirty case, so ADR-0037's
  maintenance-ledger guarantees are unchanged.
- The fuzzy shell-attribution heuristic that put a phantom path into the attributed
  set can no longer force a commit demand on a clean tree; its own accuracy becomes
  a separate, non-load-bearing concern.

## Alternatives Considered

- **Fix the shell attribution instead, staying purely within ADR-0037.**
  Correcting the parser so quoted command data is not misread as a touched path
  removes the phantom without consulting git state, keeping ADR-0037 intact.
  Rejected as the primary fix: the attribution is a fuzzy text heuristic that has
  been repeatedly patched and re-broken, and a guaranteed working-tree floor is
  correct regardless of how the attributed set is computed. Parser accuracy remains
  a separate deferred concern, not a blocker for this defect.
- **Gate the commit action on the full sealed-commit resolved scope.** Rejected as
  over-scoped: session-scoped resolution reintroduces "git arbitrates which files
  belong to whom" across worktree and shared-branch contexts and expands the blast
  radius across many checkpoint use cases, where a clean/dirty floor closes the
  reported defect with a single guaranteed condition.
