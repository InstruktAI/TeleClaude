# Requirements: unified-roadmap-assembly

## Goal

Unify roadmap and todo data assembly into a single core function to ensure consistency between the CLI, API, and TUI.

## Scope

### In scope:

- Extract `assemble_roadmap` function to `teleclaude/core/roadmap.py`.
- Update `command_handlers.list_todos` to use `assemble_roadmap`.
- Update `telec.py` to use `assemble_roadmap` for `telec roadmap`.
- Add `--include-icebox` and `--icebox-only` flags to `telec roadmap`.
- Add `--json` output support to `telec roadmap`.

### Out of scope:

- Remote wire transport changes (beyond enabling JSON output).
- TUI rendering changes.

## Success Criteria

- [ ] `assemble_roadmap` exists and returns `list[TodoInfo]`.
- [ ] `command_handlers.list_todos` is a thin wrapper.
- [ ] `telec roadmap` shows rich data (DOR, build status, etc.) matching the TUI/API.
- [ ] `telec roadmap --json` outputs structured JSON.
- [ ] `telec roadmap --include-icebox` works.
- [ ] `telec roadmap --icebox-only` works.

## Constraints

- Must use existing `TodoInfo` model.
- Must preserve existing TUI behavior via API.

## Risks

- Regression in TUI data if extraction misses details.
