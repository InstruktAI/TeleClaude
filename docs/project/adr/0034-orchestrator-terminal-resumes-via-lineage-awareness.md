---
date: '2026-06-11'
description: "The in-line work→prepare drift bounce resumes via the orchestrator's own lineage awareness, not via runtime state. The PREPARED terminal emits cleanup commands plus a lineage-conditioned self-end-vs-resume reminder and does not detect which case applies. A runtime-state marker on the todo and worktree-presence inference were both rejected: the bounce is one continuous in-line session and precedes worktree creation, so neither is needed."
number: '34'
visibility: 'public'
---

# ADR-0034: Orchestrator Terminal Resumes via Lineage Awareness — ADR

## Context

The prepare state machine's PREPARED terminal once emitted a fabricated decision
prompt — "Continue preparation work, or start the build/review cycle with
`telec todo work {slug}`." A terminal phase has no such decision to offer on a
fresh prepare: initiating future work is not the orchestrator's to do, and the
prompt caused an orchestrator to start the build cycle unprompted, against the
session-lifecycle principle that a terminal reports what is true and self-ends.

There is exactly one legitimate case where reaching PREPARED should resume work:
a work orchestrator that bounced **in-line** to prepare to reconcile artifact
drift and now needs to continue. The work state machine runs its drift check
before any worktree is created (`_check_work_entry_drift` precedes
`_ensure_worktree_ready`), and the bounce instruction it emits already tells the
orchestrator to call `telec todo work {slug}` once prepare reaches PREPARED
again. The bounce is therefore one continuous session that carries its own
resume instruction in context — no information is lost across it.

The question was how the PREPARED terminal should distinguish the terminal-prepare
case (self-end) from the in-line-bounce case (resume work) without re-introducing
a speculative next-step prompt.

## Decision

The PREPARED terminal does not detect the bounce. It states the objective outcome
(prepared; drift reconciled), emits the cleanup commands (end each live slug
worker, then the orchestrator self-end), and carries a lineage-conditioned
reminder: an orchestrator that reached PREPARED as a terminal prepare run
self-ends; an orchestrator that bounced here in-line from `telec todo work {slug}`
resumes work instead of self-ending. The machine states the condition; the
orchestrator, which alone knows its own lineage, applies it. The work
finalize-handoff terminal follows the same shape — it states objective completion
rather than a negative "do not call X again," and routes its cleanup through the
same shared session-cleanup formatter.

## Consequences

- The terminal output never targets a non-reality, so an orchestrator cannot act
  on a fabricated next-step instruction.
- The one legitimate resume path is preserved without the machine inspecting
  runtime state: the bounced orchestrator already holds its resume instruction.
- The "end children + end self" command block is emitted by one shared formatter,
  so the four terminals cannot drift in how they spell cleanup.
- The cost is that correctness now depends on the orchestrator honoring its own
  lineage when it reads the conditional reminder, rather than on a machine-enforced
  branch. This is acceptable because the bounce is in-line — the lineage is in the
  orchestrator's own context, not reconstructed from external state — and the
  terminal-prepare case (self-end) is the safe default if the reminder is ignored.

## Alternatives Considered

- **A runtime-state marker on the todo** recording that a work session bounced
  into prepare, read back by the PREPARED terminal to choose self-end vs. resume.
  Rejected: it abuses the todo for transient runtime state, and the bounce is an
  in-line continuation that needs no durable marker — the resuming orchestrator
  already knows.
- **Worktree-presence inference** — treating the existence of a `trees/{slug}`
  worktree as evidence of a prior work attempt. Rejected: the work drift check
  bounces before any worktree is created, so at PREPARED time no worktree exists
  to observe; the signal would always be absent precisely when it is needed.
