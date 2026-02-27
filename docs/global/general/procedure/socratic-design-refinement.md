---
description: 'Refine ideas into explicit, approved designs through focused questioning and trade-off analysis before writing implementation code.'
id: 'general/procedure/socratic-design-refinement'
scope: 'global'
type: 'procedure'
---

# Socratic Design Refinement — Procedure

## Goal

Transform a vague intent or problem statement into a clarified, approved design before any implementation work begins. Prevent rework from hidden assumptions by surfacing trade-offs and confirming alignment first.

Hard gate: do not start implementation until a design is presented and approved.

## Preconditions

- A problem statement or user intent is available.
- Current project context is accessible (existing architecture, constraints, patterns).
- Success criteria and known limitations are at least partially understood.

## Steps

1. **Inspect context** — Read relevant files, examine existing patterns, constraints, and adjacent behavior before asking anything.
2. **Clarify** — Ask one focused question per turn to reduce ambiguity. Do not ask multiple questions at once.
3. **Build shared understanding** — Confirm goals, boundaries, and acceptance criteria. Surface assumptions explicitly.
4. **Propose approaches** — Present 2–3 viable approaches with explicit trade-offs for each.
5. **Recommend** — Choose one approach with concrete reasoning. Name the risks of the alternatives.
6. **Present the design** — Structure it in sections: architecture, data flow, error handling, tests.
7. **Confirm approval** — Do not proceed to implementation without explicit design approval.
8. **Revise if needed** — If approval is not given, revise and repeat from the appropriate step.

Socratic prompts to guide refinement:

- What user outcome matters most?
- What should be explicitly out of scope?
- What failure modes are unacceptable?
- What is the smallest valuable version?
- Which constraints are fixed vs. negotiable?

## Outputs

- Clarified requirements with assumptions surfaced.
- 2–3 viable approaches with trade-offs and a recommendation.
- Approved design summary ready for implementation planning.
- Documented decisions and open questions.

## Recovery

- If the user cannot approve because the design is unclear, return to step 4 and restructure the presentation.
- If requirements keep expanding, apply scope containment: name what is in vs. out and confirm boundaries before proceeding.

Anti-patterns to reject:

| Anti-pattern                  | Risk introduced                   | Correct behavior              |
| ----------------------------- | --------------------------------- | ----------------------------- |
| Jumping into code immediately | Rework from hidden assumptions    | Design first, then implement  |
| Asking many questions at once | User overload and shallow answers | One focused question per turn |
| Single-solution thinking      | Missed better trade-offs          | Compare multiple approaches   |
| Vague approval checks         | Misaligned implementation         | Seek explicit design approval |
