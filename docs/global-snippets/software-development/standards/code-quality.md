---
description:
  Architecture, typing, contracts, state management, error handling. Generic
  quality standards for all code.
id: software-development/standards/code-quality
scope: domain
type: policy
---

# Code Quality Standards

## Project Awareness

1. Always follow the project's existing configuration (pyproject, tsconfig, eslint, ruff, etc.)
2. Use only approved dependencies, import patterns, naming, and formatting
3. Mirror the repository's structure and conventions
4. Don't introduce new frameworks or architectural patterns

## Architecture & Structure

1. Keep one clear responsibility per module, function, or class
2. Separate business logic, infrastructure, and UI
3. Depend on abstractions, not implementations
4. Avoid circular dependencies
5. Prefer composition over inheritance
6. Keep the public surface small and explicit
7. Choose the simplest design that fully delivers the outcome

## Functions & Behavior

1. Use pure functions for business logic, no hidden side effects
2. Parameters and return types must be explicit
3. Keep parameter lists small; use structured objects when complexity grows
4. Apply Command-Query Separation: read or write, never both
5. Default to explicit typing and deterministic outputs

## Typing & Contracts

1. **Always type everything**
   - TypeScript: strict types, no `any`, typed lists and dicts
   - Python: no `Any` or `object`, typed lists and dicts, modern syntax (`list`, `dict`, `|`)

2. Define structured data models (interfaces, dataclasses, schemas)
3. Enforce invariants so illegal states are unrepresentable
4. Validate at system boundaries; fail early and clearly
5. Never return `None` or `null` for errors; raise or return Result/Option

### Contract-First Behavior

- Treat contracts as laws. Missing required data is a bug, not a branch
- Do not add fallbacks or silent defaults unless the contract explicitly defines them
- Defaults belong at the boundary where they are defined, not scattered through call chains
- Never swallow exceptions. If the system can continue safely, log explicitly and continue; otherwise fail fast

### Signature Fidelity (Non-Negotiable)

- Signatures are contracts, not heuristics. Do not interpret, normalize, or "clean" signature fields
- Persist and forward signature values exactly as provided (within declared types)
- Never coerce empty string ↔ null or drop fields to "improve" data quality

## State & Dependencies

1. Prefer explicit state ownership; avoid hidden or implicit state
2. Avoid global mutable state except defined singletons
3. Initialize state explicitly, never on import
4. Pass dependencies explicitly; don't hide them in globals
5. Don't create Manager, Service, or Helper classes unless truly required

## Error Handling & Reliability

1. Fail fast with clear diagnostics when contracts are violated
2. Validate early and close to input
3. Commands change state; queries do not
4. Keep recovery logic explicit and minimal

## Async / Concurrency

1. Use async/await over callbacks
2. Aggregate concurrent operations with gather or Promise.all
3. Use explicit async context managers for resources

## Output Discipline

1. Conform to existing naming and formatting automatically
2. Don't add unused imports or extra utilities
3. Never contradict the project's configuration
