---
description: Practical guidance for applying code-quality policy in day-to-day work.
id: software-development/guide/code-quality-practices
requires:
  - software-development/standards/code-quality
scope: domain
type: guide
---

# Code Quality Practices

## Configuration Alignment

- Follow the repository’s configuration and established conventions.
- Introduce new patterns only when they are required by the intent.

## Architecture & Structure

- Keep one responsibility per module, function, or class.
- Separate core logic from interfaces and operational concerns.
- Prefer designs that are explicit, verifiable, and easy to reason about.

## Contracts & Types

- Make contracts explicit and enforce invariants at boundaries.
- Preserve signature fidelity across all call chains.
- Use structured models to make illegal states unrepresentable.

## State & Dependencies

- Assign explicit ownership to state and its lifecycle.
- Avoid implicit global state or import‑time side effects.
- Pass dependencies explicitly and keep boundaries visible.

## Error Handling

- Fail fast on contract violations with clear diagnostics.
- Keep recovery logic explicit and minimal.
- Make error posture clear: when to stop, when to continue, and why.

## Concurrency

- Preserve deterministic outcomes under concurrency.
- Aggregate parallel work explicitly and keep ordering intentional.
- Protect shared state with explicit ownership or isolation.

## Observability

- Log boundary events and failures with enough context to diagnose.
- Prefer clarity over volume; log what changes decisions.
