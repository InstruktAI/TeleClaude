# Requirements: rlf-core-machines

## Goal

Decompose two large state machine files into smaller, focused modules without any behavior changes.

## Scope

### In scope:
- `teleclaude/core/next_machine/core.py` (4,952 lines) → split into ~10 focused modules
- `teleclaude/core/integration/state_machine.py` (1,204 lines) → split into 2–3 modules
- Update `__init__.py` re-exports to maintain backward-compatible import paths
- Update internal imports in `prepare_helpers.py` and `integration/state_machine.py` as needed

### Out of scope:
- No behavior changes of any kind
- No test changes (test suite rebuild is a separate todo)
- No changes to public APIs

## Success Criteria

- [x] No module exceeds 800 lines (hard ceiling)
- [x] `make lint` passes
- [x] `make test` passes
- [x] All public imports from `teleclaude.core.next_machine` and `teleclaude.core.integration.state_machine` still resolve
- [x] No circular imports introduced
- [x] Runtime smoke: daemon starts, TUI renders, CLI responds

## Constraints

- Strict no-behavior-change policy
- Use `__init__.py` re-exports for backward-compatible import paths
- Commit atomically per split module or tightly-coupled group

## Risks

- Circular import if shared utilities are placed in the wrong layer
- Private functions (`_emit_prepare_event`, `_prepare_worktree`) referenced externally — must remain importable from `core.py`
