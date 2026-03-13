# Requirements: rlf-adapters

## Goal

Structurally decompose three large adapter files into smaller, concern-grouped
modules using the mixin-based package pattern already proven by the telegram/
package. No behavior changes — pure structural refactoring.

## Scope

### In scope:
- Split `teleclaude/adapters/discord_adapter.py` (2,951 lines) into
  `teleclaude/adapters/discord/` package with mixin classes.
- Split `teleclaude/adapters/telegram_adapter.py` (1,368 lines) by adding new
  mixin submodules to the existing `teleclaude/adapters/telegram/` package.
- Split `teleclaude/adapters/ui_adapter.py` (1,048 lines) into
  `teleclaude/adapters/ui/` package with mixin classes.
- Maintain backward-compatible import paths via `__init__.py` re-exports.
- No circular dependencies introduced.

### Out of scope:
- Test changes (test suite rebuild is a separate todo).
- Behavior changes of any kind.
- Adding new features or fixing bugs.

## Success Criteria

- [ ] No module exceeds 800 lines (hard ceiling).
- [ ] `make lint` passes (ruff, pyright, mypy, pylint).
- [ ] `make test` passes.
- [ ] All existing import paths still resolve (backward-compatible re-exports).
- [ ] No circular dependencies.

## Constraints

- Follow the telegram/ mixin pattern: concern-specific Mixin classes, each in
  its own submodule, re-exported from the package `__init__.py`.
- Use `if TYPE_CHECKING:` guards in mixins to avoid runtime circular imports.
- Commit atomically per file or tightly-coupled group.
- Runtime smoke: daemon starts, TUI renders, CLI responds.

## Risks

- Type checking (pyright/mypy) may flag mixin self-references; mitigate with
  TYPE_CHECKING guard declarations of required host attributes.
- MRO complications if mixin order is wrong; keep base class (`UiAdapter`) last.
- Import cycles if mixin imports its own host class at runtime.
