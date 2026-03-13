# Requirements: rlf-tui

## Goal

Structurally decompose six oversized TUI files into focused submodules without changing
any runtime behavior.

## Scope

### In scope:
- `teleclaude/cli/tui/app.py` (1,467 lines) → 3 mixin submodules
- `teleclaude/cli/tui/pane_manager.py` (1,286 lines) → 2 mixin submodules
- `teleclaude/cli/tui/views/sessions.py` (1,256 lines) → 2 mixin submodules
- `teleclaude/cli/tui/views/config.py` (1,086 lines) → 2 mixin submodules
- `teleclaude/cli/tui/animations/general.py` (1,114 lines) → 2 standalone submodules
- `teleclaude/cli/tui/views/preparation.py` (1,070 lines) → 1 mixin submodule

### Out of scope:
- Behavior changes of any kind
- Test changes (handled by separate todo)
- Files outside `teleclaude/cli/tui/`
- Other large files in the codebase

## Success Criteria

- [x] All 6 target files reduced to ≤800 lines (hard ceiling)
- [x] `__init__.py` re-exports maintain backward-compatible import paths
- [x] No circular dependencies introduced
- [x] `make lint` does not gain new failures from TUI files
- [x] `make test` passes
- [x] Runtime smoke: TUI imports without error

## Constraints

- No behavior changes. Only structural decomposition.
- Target: no module over ~500 lines (soft), hard ceiling 800 lines.
- Use `__init__.py` / module re-exports for backward-compatible import paths.
- No circular dependencies.
- No test changes.
- Commit atomically per file or tightly-coupled group.

## Risks

- Mixin pattern with strict mypy: mitigated by existing `disable_error_code` overrides for `teleclaude.cli.tui.*`
- Circular imports: mitigated by keeping imports in mixin files unidirectional
- Textual message handler discovery: Textual uses MRO to find `on_*` methods → mixin methods will be found ✓
