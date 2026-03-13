# Requirements: rlf-cli

## Goal

Decompose two oversized CLI files into smaller, maintainable modules while preserving all behavior and import contracts.

## Scope

### In scope:
- Split `teleclaude/cli/telec.py` (4,401 lines) into `teleclaude/cli/telec/` package
- Split `teleclaude/cli/tool_commands.py` (1,458 lines) into `teleclaude/cli/tool_commands/` package
- Backward-compatible re-exports via `__init__.py` for all currently-imported symbols
- Update `pyproject.toml` lint exceptions to use new module paths
- Update `teleclaude/cli/tool_commands.py` lazy import of `_handle_revive`

### Out of scope:
- Behavior changes
- Test changes (test suite rebuild is a separate todo)
- Refactoring logic within handler functions

## Success Criteria

- [x] No module exceeds 800 lines (hard ceiling)
- [x] All external imports from old paths resolve via `__init__.py` re-exports
- [x] `make lint` passes
- [x] `make test` passes
- [x] `telec` entry point `teleclaude.cli.telec:main` still works
- [x] Runtime smoke: CLI responds

## Constraints

- No behavior changes — only structural decomposition
- Target: no module over ~500 lines (soft), hard ceiling 800 lines
- Use `__init__.py` re-exports for backward-compatible import paths
- No circular dependencies
- No test changes
- Commit atomically per file or tightly-coupled group

## Risks

- Circular import risk when handlers import from `__init__.py` (mitigated by importing shared state lazily or from leaf modules)
- `tool_commands.py` lazy-imports `telec as telec_cli` and calls `_handle_revive` — must update to new location
