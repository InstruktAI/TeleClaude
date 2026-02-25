---
name: receiving-code-review
description: Technical rigor when handling review feedback. Use when receiving code review findings, before implementing suggestions.
---

# Receiving Code Review

## Purpose

Handle review feedback with technical rigor: verify claims, clarify ambiguity, and implement only validated changes.

## Scope

Use whenever review findings arrive from peers, automated reviewers, or external contributors.

Core discipline:

- Verify before accepting.
- Ask before assuming.
- Prefer correctness over performative agreement.

## Inputs

- Review comments and requested changes.
- Relevant code context and existing behavior.
- Project constraints and prior architectural decisions.

## Outputs

- Clarified understanding of each review item.
- Validated implementation decisions (accept, adjust, or reject with rationale).
- Code updates and verification evidence for accepted items.
- Documented technical pushback for incorrect or harmful suggestions.

## Procedure

1. Read all feedback without immediate implementation.
2. Restate each item as a concrete technical requirement.
3. Clarify ambiguous items before changing code.
4. Validate each suggestion against current code behavior, tests, and constraints.
5. Implement accepted items one at a time and verify each change.
6. For incorrect suggestions, provide concise technical reasoning and an alternative.
7. Escalate when feedback conflicts with explicit architectural decisions.

Pushback protocol:

- State observed behavior.
- State why the suggested change is incorrect, risky, or out of scope.
- Provide evidence (code path, tests, platform constraints).
- Offer a safer alternative when available.

Anti-patterns to reject:

| Anti-pattern                  | Risk introduced                                     | Correct behavior                  |
| ----------------------------- | --------------------------------------------------- | --------------------------------- |
| Performative agreement        | Hides technical disagreement and causes bad changes | Respond with technical evaluation |
| Blindly applying all comments | Breaks behavior and scope                           | Validate each item first          |
| Implementing unclear items    | Rework and wrong outcomes                           | Clarify before coding             |
| Avoiding pushback             | Known defects are accepted                          | Push back with evidence           |
