---
description: 'Practical guidance for applying code-quality policy in day-to-day work.'
id: 'software-development/policy/code-quality-practices'
scope: 'domain'
type: 'policy'
---

# Code Quality Practices — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/code-quality.md
- @~/.teleclaude/docs/software-development/principle/design-fundamentals.md

## Rules

### Structure and Responsibility

- Follow the repository's configuration and established conventions.
- Introduce new patterns only when required by the intent (**YAGNI**).
- **SRP**: each module, function, or class has one reason to change. If a description requires "and," split it.
- Separate core logic from interfaces and operational concerns (**Separation of Concerns**).
- Prefer designs that are explicit, verifiable, and easy to reason about (**KISS**). Essential complexity is justified; accidental complexity is not.
- Group by domain concern, not by technical category (**High Cohesion**). No `utils` or `helpers` modules.
- Build complex behavior by combining simple pieces, not by extending class hierarchies (**Composition over Inheritance**).

### Dependencies and Boundaries

- High-level modules define shapes; low-level modules implement them (**DIP**). Core never imports from adapters.
- Pass dependencies through parameters or constructors (**Loose Coupling**). Do not import singletons.
- Only talk to immediate collaborators, not to their internals (**Law of Demeter**). Prefer one dot over a chain.
- Make contracts explicit and enforce invariants at boundaries.
- Preserve signature fidelity across all call chains.

### State and Data

- Use structured models to make illegal states unrepresentable.
- Assign explicit ownership to state and its lifecycle (**Encapsulation**).
- Default to immutable data. Keep mutable state in a single owner (**Immutability Preference**).
- Avoid implicit global state or import-time side effects.

### Duplication and Abstraction

- Extract shared **knowledge** to a single owner (**DRY**). Same business rule in two places will diverge.
- Tolerate duplicated **code** when the alternative couples unrelated domains. Duplication is cheaper than the wrong abstraction.
- Do not create abstractions for patterns that occur once (**YAGNI**). Wait for a second real consumer.

### Error Handling and Recovery

- Fail fast on contract violations with clear diagnostics. Catch specific exceptions; let programming errors crash.
- Keep recovery logic explicit and minimal.
- Make error posture clear: when to stop, when to continue, and why.
- Validate at system boundaries; trust within (**Fail Fast** at boundaries, not everywhere).

### Concurrency

- Preserve deterministic outcomes under concurrency.
- Aggregate parallel work explicitly and keep ordering intentional.
- Protect shared state with explicit ownership or isolation.

### Observability

- Log boundary events and failures with enough context to diagnose.
- Prefer clarity over volume; log what changes decisions.

### Naming and Comments

- Name for semantics, not origin. Names must make sense to someone who never saw the feature request or ticket that motivated the change.
- Comments describe the present, never the past. No "removed X", "used to do Y", "added for Z". Git is the history; comments explain what is here now.
- When removing code, remove it completely. No `_unused` renames, no `// removed` comments, no re-exports for backward compatibility unless explicitly required.

### Testing Alignment

- In tests, assert observable behavior and contracts, not narrative documentation wording.
- Exact-string test assertions are acceptable only when runtime behavior depends on exact tokens (protocol markers, schema keys, command literals, or reference prefixes).

## Rationale

Apply the code-quality policy and design principles consistently in daily work. Named principles provide shared vocabulary for structural reasoning; these rules translate them into concrete habits.

## Scope

Applies to all code in the repository.

## Enforcement

Violations should be fixed before merge; reviewers enforce this policy.

## Exceptions

None. If a deviation is required, document the rationale and get explicit approval.
