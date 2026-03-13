# Requirements: rlf-core-data

## Goal

Structurally decompose three large data-layer files in `teleclaude/core/` into smaller,
maintainable modules without any behavior changes.

## Scope

### In scope:
- `teleclaude/core/db.py` (2,599 lines) → `teleclaude/core/db/` package
- `teleclaude/core/command_handlers.py` (2,031 lines) → `teleclaude/core/command_handlers/` package
- `teleclaude/core/models.py` (1,112 lines) → `teleclaude/core/models/` package
- `__init__.py` re-exports preserving all existing import paths

### Out of scope:
- Behavior changes of any kind
- Test file changes (test suite rebuild is a separate todo)
- Changes to files outside the three targets

## Success Criteria

- [ ] No module in the new packages exceeds 800 lines (hard ceiling)
- [ ] All existing imports work unchanged via `__init__.py` re-exports
- [ ] `make lint` passes (ruff, pyright, mypy, pylint)
- [ ] `make test` passes (no regressions)
- [ ] No circular dependencies introduced

## Constraints

- No behavior changes; structural decomposition only
- Target: no module over ~500 lines (soft), hard ceiling 800 lines
- Use `__init__.py` re-exports for backward-compatible import paths
- No circular dependencies introduced
- No test changes
- `make lint` and type checking must pass after decomposition
- Commit atomically per file/package
- Runtime smoke: daemon starts, TUI renders, CLI responds

## Risks

- `db.py` has 45 importers; any broken re-export causes runtime failures
- Mixin/multi-file Db class must satisfy mypy, pyright, and pylint
- Circular imports possible if dependency ordering is wrong
