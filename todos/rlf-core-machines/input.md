# Input: rlf-core-machines

<!-- Seeded from parent refactor-large-files approved requirements. -->

## Problem

Two state machine files in core need structural decomposition.

## Targets

| File | Lines | Structure |
|------|-------|-----------|
| `teleclaude/core/next_machine/core.py` | 4,168 | 12 enums/dataclasses + 122 functions spanning distinct concerns |
| `teleclaude/core/integration/state_machine.py` | 1,183 | Integration phase state machine |

Total: ~5,351 lines.

## Context

- `core/next_machine/` is already a package. `__init__.py` re-exports from `core.py` using wildcard import. `prepare.py` and `work.py` already exist as completed splits — this is the precedent pattern.
- `core.py` has clear concern groups: state I/O (~270 lines), roadmap management (~585 lines), icebox management (~100 lines), delivered/delivery (~157 lines), worktree operations (~355 lines), build gates (~217 lines), slug resolution (~168 lines), prepare phase steps (~600 lines), formatting/output (~160 lines).
- Import fanout: 12 files import from `teleclaude.core.next_machine`.
- `core/integration/` is also a package. `state_machine.py` is the integration phase state machine.

## Shared constraints (from parent)

- No behavior changes. Only structural decomposition.
- Target: no module over ~500 lines (soft), hard ceiling 800 lines.
- Use `__init__.py` re-exports for backward-compatible import paths.
- No circular dependencies introduced.
- No test changes (test suite rebuild is a separate todo).
- `make lint` and type checking must pass after decomposition.
- Commit atomically per file or tightly-coupled group.
- Runtime smoke: daemon starts, TUI renders, CLI responds.
