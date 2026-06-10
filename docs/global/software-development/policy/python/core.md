---
description: 'Python typing, data handling, error patterns, async, idioms. Modern syntax, explicit types, pure functions.'
visibility: 'public'
---

# Core — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/python/tooling.md

## Rules

- Type everything. No untyped dicts. No implicit `Any`.
- Every function has explicit parameter and return types.
- Use structured data models (dataclass, TypedDict, Protocol) for non-trivial data.
- Model a fixed set of related string values as a `StrEnum` (not scattered module constants, not a namespacing class); reference members, never inline the literal. Do not add a lint/guard to police inlined literals — that is a lint-as-type-substitute anti-pattern; the `StrEnum` makes the bare literal a type error for free. See `code-quality-practices` → State and Data.
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
- Keep package `__init__.py` files as import/export surfaces; move implementation into dedicated modules.
- Follow project formatter and linter rules exactly.
- Keep all imports at module top level.
- Conform to existing naming and patterns.
- Do not shell out (`subprocess.run`, `subprocess.Popen`, `subprocess.call`, `os.system`, `os.popen`) when a Python-native solution exists. Use `pathlib` and `shutil` for filesystem operations. Use the project's git helpers (e.g. `_run_git`, `_run_git_cmd`) for git operations. Only invoke subprocesses when no Python API or project helper exists for the operation. Any subprocess call requires a comment justifying why a native approach is not viable.
- In uv-managed repositories, invoke Python project tools through `uv run <tool> ...`; see the Python tooling policy for command boundaries.

## Rationale

Use consistent Python practices for typing, structure, and error handling to keep behavior predictable for reviewers and agents.

## Scope

Applies to all Python code in the repository, including scripts and tooling.

## Enforcement

If a change violates this policy, refactor before merge.

## Exceptions

None. If a deviation is required, document the rationale and get explicit approval.
