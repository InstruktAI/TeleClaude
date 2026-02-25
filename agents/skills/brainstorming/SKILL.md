---
name: brainstorming
description: Socratic design refinement before implementation. Use before any creative work - features, components, or behavior changes.
---

# Brainstorming

## Purpose

Refine ideas into explicit designs through focused questioning and trade-off analysis before writing implementation code.

## Scope

Apply before creative implementation work such as new features, UI components, workflows, and behavior changes.

Hard gate:

- Do not start implementation until a design is presented and approved.

## Inputs

- Problem statement or user intent.
- Current project context (existing architecture, constraints, patterns).
- Success criteria and known limitations.

## Outputs

- Clarified requirements with assumptions surfaced.
- 2-3 viable approaches with trade-offs and a recommendation.
- Approved design summary ready for implementation planning.
- Documented decisions and open questions.

## Procedure

1. Inspect current context: relevant files, existing patterns, constraints, and adjacent behavior.
2. Ask one clarifying question at a time to reduce ambiguity.
3. Build shared understanding of goals, boundaries, and acceptance criteria.
4. Propose 2-3 approaches with explicit trade-offs.
5. Recommend one approach with concrete reasoning.
6. Present the design in sections (architecture, data flow, error handling, tests).
7. Confirm approval before any implementation work begins.
8. If approval is not given, revise and repeat from the appropriate step.

Socratic prompts to guide refinement:

- What user outcome matters most?
- What should be explicitly out of scope?
- What failure modes are unacceptable?
- What is the smallest valuable version?
- Which constraints are fixed vs negotiable?

Anti-patterns to reject:

| Anti-pattern                  | Risk introduced                   | Correct behavior              |
| ----------------------------- | --------------------------------- | ----------------------------- |
| Jumping into code immediately | Rework from hidden assumptions    | Design first, then implement  |
| Asking many questions at once | User overload and shallow answers | One focused question per turn |
| Single-solution thinking      | Missed better trade-offs          | Compare multiple approaches   |
| Vague approval checks         | Misaligned implementation         | Seek explicit design approval |
