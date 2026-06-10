---
description: 'Python project tool invocation policy for uv-managed repositories. Standardizes pytest, mypy, pyright, hooks, and TeleClaude quality commands.'
visibility: 'public'
---

# Python Tooling — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/python/core.md

## Rules

1. **Use uv as the Python project tool boundary.** In a uv-managed repository,
   Python project tools must be invoked through `uv run`.
2. **Use tool entrypoints by default.** Invoke Python dev tools as
   `uv run <tool> ...` unless the tool's documentation or project config
   requires a different command.
3. **Do not use bare project tools.** Commands such as `pytest`, `mypy`,
   `pyright`, `ruff`, or project scripts must not be invoked by bare executable
   name from daemon code, hooks, jobs, or TeleClaude quality wrappers.
4. **Do not bind project tools to the TeleClaude runtime interpreter.**
   `sys.executable -m <tool>` is not the default for project quality tooling
   in uv-managed repositories because the TeleClaude runtime interpreter and
   the project tool environment are separate concerns.
5. **Keep command wrappers thin.** `telec code lint`, `telec code test`, hooks,
   and Make targets may choose targets, flags, and ordering, but tool versions
   and executable resolution belong to the uv-managed project environment.
6. **Centralize exceptions.** If a tool cannot be run through `uv run <tool>`,
   document the reason at the wrapper site and in the relevant project tooling
   policy before adding an exception.

Default invocations:

| Tool purpose | Default invocation   |
| ------------ | -------------------- |
| Tests        | `uv run pytest ...`  |
| Mypy         | `uv run mypy ...`    |
| Pyright      | `uv run pyright ...` |
| Ruff         | `uv run ruff ...`    |

## Rationale

`uv run` is the project-environment boundary for uv-managed Python
repositories. It resolves tools from the project's declared dependency set and
avoids split-brain behavior between interactive shells, daemon launch
environments, hooks, jobs, and CI.

Bare executable names depend on ambient `PATH`. `sys.executable -m <tool>`
depends on the interpreter currently running TeleClaude. Neither is the
project-level contract in a uv-managed repository.

## Scope

Applies to Python project tooling invoked by source code, hooks, jobs, Make
targets, CI commands, and agent instructions in uv-managed repositories.

## Enforcement

Reviewers must reject new bare Python project-tool invocations and new
`sys.executable -m <tool>` invocations for project quality tools unless an
exception is documented.

## Exceptions

None by default.
