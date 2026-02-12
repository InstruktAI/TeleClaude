---
description: 'Practical guidance for applying code-quality policy in day-to-day work.'
id: 'software-development/policy/code-quality-practices'
scope: 'domain'
type: 'policy'
---

# Code Quality Practices — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/code-quality.md

## Rules

- Follow the repository's configuration and established conventions.
- Introduce new patterns only when they are required by the intent.
- Keep one responsibility per module, function, or class.
- Separate core logic from interfaces and operational concerns.
- Prefer designs that are explicit, verifiable, and easy to reason about.
- Make contracts explicit and enforce invariants at boundaries.
- Preserve signature fidelity across all call chains.
- Use structured models to make illegal states unrepresentable.
- Assign explicit ownership to state and its lifecycle.
- Avoid implicit global state or import-time side effects.
- Pass dependencies explicitly and keep boundaries visible.
- Fail fast on contract violations with clear diagnostics.
- Keep recovery logic explicit and minimal.
- Make error posture clear: when to stop, when to continue, and why.
- Preserve deterministic outcomes under concurrency.
- Aggregate parallel work explicitly and keep ordering intentional.
- Protect shared state with explicit ownership or isolation.
- Log boundary events and failures with enough context to diagnose.
- Prefer clarity over volume; log what changes decisions.
- Name for semantics, not origin. Names must make sense to someone who never saw the feature request or ticket that motivated the change.
- Comments describe the present, never the past. No "removed X", "used to do Y", "added for Z". Git is the history; comments explain what is here now.
- When removing code, remove it completely. No `_unused` renames, no `// removed` comments, no re-exports for backward compatibility unless explicitly required.
- In tests, assert observable behavior and contracts, not narrative documentation wording.
- Exact-string test assertions are acceptable only when runtime behavior depends on exact tokens (protocol markers, schema keys, command literals, or reference prefixes).

## Rationale

Apply the code-quality policy consistently in daily work. These rules translate the policy into concrete habits for structure, error handling, state management, and concurrency.

## Scope

Applies to all code in the repository.

## Enforcement

Violations should be fixed before merge; reviewers enforce this policy.

## Exceptions

None. If a deviation is required, document the rationale and get explicit approval.
