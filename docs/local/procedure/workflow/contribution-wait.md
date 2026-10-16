---
description: Keep an adopted proposal's builder available for the owning orchestrator's review feedback and continuation.
visibility: internal
delivered_by:
  - reviewed-pr-contributions
role: builder
parameters:
  - name: adoption_id
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

Hold the intake builder assignment for the retained imported proposal while
its upstream reviewer assesses the subject.

## Preconditions

- The assignment identifies the adoption record and retained proposal.
- The session starts with upstream-owned instructions and configuration.

## Steps

1. Retain the assigned adoption and proposal identity as the scope of this
   session. The assignment is waiting for its upstream assessment; settle into
   stillness under the no-output-turn policy.
2. The owning intake operation settles this assignment before handing the
   retained source and evidence to ordinary preparation/work. The later work
   driver's builder resumes that source inside its own claiming group
   (`local/projects/teleclaude/spec/feature/workflow/item-lifecycle`).

## Outputs

- A retained intake builder waiting while the proposal is assessed.
- Source retained for the ordinary work driver's builder at handoff.

## Recovery

Report a changed proposal identity or unavailable source with its evidence to
the owning intake operation (`general/procedure/orchestration`).
