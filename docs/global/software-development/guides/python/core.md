---
description:
  Python typing, data handling, error patterns, async, idioms. Modern syntax,
  explicit types, pure functions.
id: software-development/guides/python/core
scope: domain
type: guide
---

# Core — Guide

## Required reads

- @~/.teleclaude/docs/software-development/standards/code-quality.md

## Goal

- Apply consistent Python practices for typing, structure, and error handling.

## Steps

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

## Outputs

- Python changes that conform to project typing and structure practices.

## Recovery

- Refactor or simplify any change that violates the guide before merge.
