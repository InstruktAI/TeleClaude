---
description: 'Python typing, data handling, error patterns, async, idioms. Modern syntax, explicit types, pure functions.'
id: 'software-development/policy/python/core'
scope: 'domain'
type: 'policy'
---

# Core — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/code-quality.md

## Rules

- Type everything. No untyped dicts. No implicit `Any`.
- Every function has explicit parameter and return types.
- Use structured data models (dataclass, TypedDict, Protocol) for non-trivial data.
- Use modern type syntax: `list[str]`, `dict[str, int]`, `str | None`.
- Do not mutate inputs in place unless the interface explicitly requires it.
- Validate at system boundaries; keep core logic pure and testable.
- Prefer dataclasses and protocols for structure; avoid mutable defaults.
- Errors are part of the contract: raise with context or return a defined Result/Option.
- Never swallow exceptions silently; use specific exception types.
- Use async only when required by I/O; keep sync/async boundaries explicit.
- Use `asyncio.gather()` for concurrency; use async context managers for resources.
- Prefer dict-based dispatch over long if/elif chains.
- Use generators for streaming or large data.
- Use context managers for resource handling.
- Avoid star imports or classes used for namespacing.
- Follow project formatter and linter rules exactly.
- Keep all imports at module top level.
- Conform to existing naming and patterns.

## Rationale

Use consistent Python practices for typing, structure, and error handling to keep behavior predictable for reviewers and agents.

## Scope

Applies to all Python code in the repository, including scripts and tooling.

## Enforcement

If a change violates this policy, refactor before merge.

## Exceptions

None. If a deviation is required, document the rationale and get explicit approval.
