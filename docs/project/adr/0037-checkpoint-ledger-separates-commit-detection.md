---
adr_status: 'accepted'
date: '2026-06-11'
description: 'The checkpoint action ledger is time-anchored and includes committed code; the authored-main-commit signal triggers only the post-commit review gate; one turn-scoped escape hatch replaces the permanent disable.'
number: '37'
visibility: 'public'
---

# Checkpoint Ledger Separates Commit Detection — ADR

## Context

The agent_stop checkpoint engine derives required actions from the files changed
in a turn. It read those files from `git diff HEAD`, scoped to the turn window.
When an agent committed code, git HEAD moved, the change-window went empty, and
every category-derived action (make restart, run tests, check logs) vanished —
leaving only the post-commit review gate. Observed live: a committed daemon-code
file surfaced no restart prompt, and the daemon had to be restarted by hand. The
checkpoint net failed exactly when it mattered most, because committed daemon code
is precisely what needs a restart.

Three concerns were entangled. The action ledger and the commit signal shared the
same git change-window, so committing erased the ledger. The authored-main-commit
marker — whose only job is to arm the review gate — was also consulted to decide
whether to suppress the commit action, blurring "what triggers review" with "what
needs doing". And a permanent, whole-session clear flag silently disabled all
checkpoints, hiding heuristic over-tightness from the human for the rest of the
session.

A precedent already existed: the integrator post-merge path sources actions from a
delivered merge delta via a session-scoped payload marker when no turn-local edits
remain. That mechanism just had not been generalized beyond the integrator.

## Decision

Separate commit detection from the time-anchored action ledger, in three parts:

- **Committed code is sourced into the action ledger.** The sealed
  `telec code commit` path records the committed file list into a session-scoped
  payload marker. The engine unions that payload into the turn's effective files,
  so category-derived maintenance actions survive the HEAD move. This generalizes
  the integrator post-merge file-sourcing precedent to any sealed commit, for any
  session. Git is consulted only as the category oracle (which file maps to which
  category), never as the arbiter of what is in-scope or done.

- **The authored-main-commit signal triggers only the review gate.** The
  authored-main-commit latch arms the post-commit review-gate surfacing and nothing
  else. Suppression of the commit action derives from commit evidence in the turn
  timeline, not from the latch.

- **One turn-scoped escape hatch.** A single clear flag, hard-cleared at
  user_prompt_submit, replaces the permanent session-wide disable. The involuntary
  recheck loop-guard is retained as the hard backstop against an evidence-miss
  spinning forever.

## Consequences

- A turn that commits daemon code surfaces the implied maintenance actions
  (make restart, plus the test and log actions of the changed categories) in
  addition to the review gate. The action ledger is no longer emptied by a commit.
- Over-tight, false-positive checkpoints become visible across turns: a turn-scoped
  hatch unblocks the agent for one turn but lets a recurring checkpoint reappear, so
  the human learns the logic regressed and can file a bug instead of a session-long
  silent suppression hiding it.
- The cost of false negatives in evidence matching rises: without a permanent hatch
  to hide a false-nag, evidence-detection coverage must be solid. The recheck
  loop-guard remains the involuntary floor, but the voluntary hatch is no longer
  load-bearing for liveness.
- The commit signal and the action ledger are now independent surfaces; a future
  change to one no longer silently perturbs the other.

## Alternatives Considered

- **Keep a boolean commit latch only.** Rejected: a boolean cannot carry the file
  identities, which are exactly what the categorizer needs to surface the right
  maintenance action. The committed-file payload is the discarded data the commit
  handler already computes.
- **Store committed files in a new sessions-table column.** Rejected: a filesystem
  payload marker matches the existing integrator-maintenance marker shape, keeps one
  mechanism, and needs no schema migration.
- **Keep the permanent clear flag and add a separate turn-scoped one.** Rejected:
  two voluntary hatches reintroduce the silent-suppression failure mode the change
  exists to remove; the requirement is exactly one, and it is temporary.
