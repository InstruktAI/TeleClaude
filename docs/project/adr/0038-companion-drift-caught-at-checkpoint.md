---
adr_status: 'accepted'
date: '2026-06-11'
description: 'Companion-edit drift (a live parent snippet reworked without its pending companion) is caught in-loop by a checkpoint presence heuristic at agent_stop, with the review lane retained as the correctness backstop.'
number: '38'
visibility: 'public'
---

# Companion-Drift Caught At The Checkpoint — ADR

## Context

A pending doc-snippet rework is authored as a companion file `<stem>.<slug>.md`
beside the live parent `<stem>.md`; at delivery the companion replaces the
parent. If an agent edits the live parent in the meantime without mirroring the
edit into the companion, the companion silently clobbers that parent edit when it
replaces the parent. Awareness, authoring discipline, and after-the-fact review
each fail this case individually: the forgetful agent does not know the companion
exists, and a review that catches the clobber runs in a different session, possibly
days later, after the editing context is gone.

The checkpoint engine already fires at agent_stop — before the editing agent walks
away — runs `git diff` over the turn's changed files, categorizes them, and blocks
with a suppressible nudge. It is the only surface that sees the parent edit at the
moment the agent still holds its context.

## Decision

Add a checkpoint heuristic that, when a turn's changed files include a live parent
snippet whose pending companion sibling exists on disk but is absent from the
changed set, surfaces an action telling the agent to mirror the edit into the
companion. The check is a filename-derived **presence** test, reusing the
companion-detection helpers the doc index already uses; the companion appearing in
the changed set suppresses it for free. The check mechanizes only the question code
may answer — is the companion in the changed set — never whether the companion is a
correct mirror of the parent. The review lane remains the backstop for mirror
correctness.

## Consequences

- Companion drift is caught in-loop, at agent_stop, by the machine — not left to
  agent memory, authoring discipline, or a later review session.
- The heuristic sits on the legal side of intelligence-boundaries: a pure presence
  check, decidable by code and fail-closed. Prose-correctness judgment stays with
  the reviewer, so the checkpoint does not become a validator in the wrong layer.
- It reuses the engine's existing `git_files` + required-action + in-turn-evidence
  suppression pattern; no new state or marker.
- The hard, in-loop enforcement of companion mirroring now lives at the checkpoint;
  a review-lane-only enforcement of the same rule becomes redundant as the primary
  gate (it stays only as the correctness backstop).
- The check fires on presence alone, so a parent edit that is _intentionally_ not
  mirrored (rare) still nags once until the agent either mirrors it or clears the
  turn-scoped hatch; this is the accepted false-nag cost of a fail-closed presence test.

## Alternatives Considered

- **Enforce only in the review lane.** Rejected as the primary gate: it catches the
  clobber after the fact, in a different session, after the editing context is gone —
  exactly when remediation is most expensive. It is kept as the correctness backstop.
- **Check companion-mirror correctness in code.** Rejected: deciding whether the
  companion faithfully mirrors the parent is prose judgment — intelligence that
  belongs in the reviewer's briefing, not in code the agent wraps. The checkpoint
  answers only the presence question.
