# Bug:

## Symptom

Right now I am watching in the work preparation view an incorrect order of the project. In the config.yaml those have a certain order. They are the trusted underscore dears property. And that order should be preserved in the three node view for both the sessions and the work preparation pane. Should all follow one unified path of course, so no hacking multiple callsites.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-02-27

## Investigation

Traced the full data flow from `config.yaml` → API → TUI:

1. `config.computer.trusted_dirs` defines the project order in YAML
2. `command_handlers.list_projects()` reads `get_all_trusted_dirs()` and builds `ProjectInfo` list in that exact order
3. The cache (`apply_projects_snapshot` / `get_projects`) preserves insertion order
4. `api_server.list_projects` returns projects in `trusted_dirs` order
5. `api_client.list_projects_with_todos()` builds `ProjectWithTodosInfo` preserving that order
6. `app.py._refresh_data()` passes the ordered list to both views

**Sessions view** (`build_tree` in `tree.py`): filters `comp_projects = [p for p in projects if p.computer == comp_name]`, then iterates in that preserved order. ✅ Correct.

**Preparation view** (`_rebuild` in `preparation.py`):

- Line 187 (old): groups projects by computer with comment "sorted alphabetically"
- Line 197 (old): `for comp_name in sorted(computer_to_projects):` — sorts computers alphabetically
- Line 219 (old): `for project in sorted(projects_in_comp, key=lambda p: p.name):` — sorts projects alphabetically by name

Both `sorted()` calls discard the `trusted_dirs` order.

## Root Cause

`teleclaude/cli/tui/views/preparation.py` explicitly re-sorted projects (and computers) alphabetically by name in `_rebuild()`, overriding the `trusted_dirs` order that was correctly preserved through the entire API chain up to that point.

Specifically:

- `sorted(computer_to_projects)` at the computer loop
- `sorted(projects_in_comp, key=lambda p: p.name)` at the project loop

## Fix Applied

In `teleclaude/cli/tui/views/preparation.py`:

1. Replaced `sorted(computer_to_projects)` with a `computer_order` list that tracks first-seen order of computers as projects arrive from `_projects_with_todos` (preserving `trusted_dirs` order).
2. Replaced `for project in sorted(projects_in_comp, key=lambda p: p.name):` with `for project in projects_in_comp:` to preserve the input order.
3. Updated the test in `tests/unit/test_tui_key_contract.py::test_preparation_tree_groups_by_computer` to assert that computers appear in insertion order (reflecting `trusted_dirs` order) rather than alphabetical order.
