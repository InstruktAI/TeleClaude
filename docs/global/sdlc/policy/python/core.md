---
description: 'Python typing, data handling, error patterns, async, idioms. Modern syntax, explicit types, pure functions.'
visibility: 'public'
---

# Core — Policy

## Rules

- Type everything. No untyped dicts. No implicit `Any`.
- Every function has explicit parameter and return types.
- Use structured data models (dataclass, TypedDict, Protocol) for non-trivial data.
- Model a fixed set of related string values as a `StrEnum` (not scattered module constants, not a namespacing class); reference members, never inline the literal. Do not add a lint/guard to police inlined literals — that is a lint-as-type-substitute anti-pattern; the `StrEnum` makes the bare literal a type error for free. See `code-quality-practices` → State and Data.
- A runtime string that is shared knowledge (`sdlc/policy/code-quality-practices` → State and Data) is a `StrEnum` member when it belongs to a closed vocabulary, and otherwise a named module-level value in its owning module, imported by every other user. A string with one use stays inline at that use; do not hoist it into a module constant. Test inputs and fixtures remain governed by the testing policy.
- Use modern type syntax: `list[str]`, `dict[str, int]`, `str | None`.
- Do not mutate inputs in place unless the interface explicitly requires it.
- Validate at system boundaries; keep core logic pure and testable.
- Prefer dataclasses and protocols for structure; avoid mutable defaults.
- Errors are part of the contract: raise with context or return a defined Result/Option.
- Inside an operation, catch the specific exception types it can act on. A supervision boundary contains every failure of its unit (`sdlc/policy/code-quality-practices`): it catches `Exception`, logs with `exc_info`, and continues, and it leaves `BaseException` uncaught so `asyncio.CancelledError`, `KeyboardInterrupt`, and `SystemExit` propagate. Every handler logs, re-raises, or converts the exception into a defined result.
- Use async only when required by I/O; keep sync/async boundaries explicit.
- Use `asyncio.gather()` for concurrency; use async context managers for resources.
- Prefer dict-based dispatch over long if/elif chains.
- **Dynamic dispatch declares its edges.** Dispatch keys come from a `StrEnum`; the dispatch table, event route, hook registration, or handler lookup is a module-level literal mapping enum members to named functions. Tables assembled through runtime registration, decorator side effects, `getattr`, or bare string keys are not permitted. This bounds the dict-dispatch preference above.
- Use generators for streaming or large data.
- Use context managers for resource handling.
- Avoid star imports or classes used for namespacing.
- A package `__init__.py` holds at most a docstring: no imports, re-exports, implementation, or import-time side effects. Consumers import every symbol from the module that owns it.
- A runnable package's entry point is its `__main__.py`. It is the one place a load may be deferred — to answer help or re-exec into the right interpreter before heavy imports — through a local import whose suppression names that reason.
- Compose imports by job: a module imports only what its own job needs. When `-X importtime` shows a consumer paying for a job it does not use, split the owner along that job. Review enforces composition; no lint or guardrail pins an import closure.
- Follow project formatter and linter rules exactly.
- Keep all imports at module top level. A local import requires an explicit project-owned exception and a same-line suppression that states the reason.
- Python linter suppressions use the narrowest same-line `noqa` form, name the suppressed rule, and state why the rule cannot apply. Broad file-level suppression is not permitted.
- Conform to existing naming and patterns.
- Do not shell out (`subprocess.run`, `subprocess.Popen`, `subprocess.call`, `os.system`, `os.popen`) when a Python-native solution exists. Use `pathlib` and `shutil` for filesystem operations. Use the project's git helpers (e.g. `_run_git`, `_run_git_cmd`) for git operations. Only invoke subprocesses when no Python API or project helper exists for the operation. Any subprocess call requires a comment justifying why a native approach is not viable.
- Reach a third-party service through an established Python client library for that service, in process. Its command-line program is never the integration path, directly or as a credential helper; a capability the library lacks is surfaced as a finding, not bridged by shelling out.
- In uv-managed repositories, invoke Python project tools through `uv run <tool> ...`; see the Python tooling policy for command boundaries.

## Rationale

Use consistent Python practices for typing, structure, and error handling to keep behavior predictable for reviewers and agents.

Dispatch that resolves through a runtime string is an edge no parser can traverse: the AST sees the emit site and the handler as unrelated statements, so import-graph and blast-radius tooling stops there. Declaring the edge keeps the code statically legible and keeps dependency tooling able to follow it.

Python runs a package's `__init__.py` on every import of any module inside it, so whatever it holds is paid by every consumer of every part of the package, and a re-export gives one symbol a second address that hides its owner from readers and from the import graph. Keeping it empty makes each import path name its owner and each consumer's cost exactly the modules it names. A pinned import closure answers a performance question with a gate, and a gate on composition pushes the next author toward copying logic around it instead of fixing the owner (`sdlc/principle/design-fundamentals`).

## Scope

Applies to all Python code in the repository, including scripts and tooling.

## Enforcement

If a change violates this policy, refactor before merge.

## Exceptions

None. If a deviation is required, document the rationale and get explicit approval.

## See Also

- ~/.teleclaude/docs/sdlc/policy/python/tooling.md
