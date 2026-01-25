---
description:
  Python typing, data handling, error patterns, async, idioms. Modern syntax,
  explicit types, pure functions.
id: software-development/guides/python/core
scope: domain
type: guide
---

# Core — Guide

## Goal

- @docs/software-development/policy/code-quality

@~/.teleclaude/docs/software-development/standards/code-quality.md

- Type everything. No untyped dicts. No implicit `Any`
- Every function has explicit parameter and return types
- Use structured data models (dataclass, TypedDict, Protocol) for all non-trivial data
- Modern type syntax: `list[str]`, `dict[str, int]`, `str | None`

- Do not mutate inputs in place; return new values unless the interface explicitly requires mutation
- Validate at system boundaries; keep core logic pure and testable
- Prefer dataclasses and protocols for structure
- Avoid mutable defaults

- Errors are part of the contract: raise with context or return a defined Result/Option
- Never swallow exceptions silently
- Use specific exception types, not bare `Exception`

- Use async only when required by I/O
- Do not mix sync/async flows without clear boundaries
- Use `asyncio.gather()` for concurrent operations
- Use async context managers for resources

- Use dict-based dispatch over long if/elif chains
- Use generators for streaming or large data
- Use context managers for resource handling
- Avoid star imports or classes used for namespacing

- Follow project formatter and linter rules exactly
- All imports at module top level (no import-outside-toplevel)
- Conform to existing naming and patterns

- TBD.

- TBD.

- TBD.

## Steps

- TBD.

## Outputs

- TBD.

## Recovery

- TBD.
