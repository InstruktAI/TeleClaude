---
description: Keep an adopted proposal's builder available for the owning orchestrator's review feedback and continuation.
visibility: internal
delivered_by:
  - reviewed-pr-contributions
role: builder
parameters:
  - name: slug
    required: true
dispatch:
  agent:
    - codex
    - claude
  thinking_mode: slow
---

# Contribution Wait — Procedure

## Required reads

@docs/local/spec/feature/workflow/contribution-adoption.md
@~/.teleclaude/docs/general/policy/no-output-turn.md

## Goal

Hold the builder assignment for the retained imported proposal while its
upstream reviewer assesses the subject.

## Preconditions

- The assignment identifies the local todo and retained proposal.
- The session starts with upstream-owned instructions and configuration.

## Steps

1. Retain the assigned todo and proposal identity as the scope of this session.
   At this entry the builder's next contribution waits on the orchestrator's
   review continuation; settle into stillness under the no-output-turn policy.
2. When the owning orchestrator supplies continuation, read its findings and
   prepared contracts. Execute the assigned repair or outstanding validation
   through the ordinary build procedure in the retained worktree.
3. Record completed work and its evidence through the ordinary builder result
   surfaces. Retain the session for the orchestrator's next review round.

## Outputs

- A retained builder available for the proposal's review continuation.
- After continuation, the ordinary builder work and completion evidence.

## Recovery

Report a changed proposal identity, unavailable worktree or unresolved contract
with its evidence to the owning orchestrator (`general/procedure/orchestration`).
