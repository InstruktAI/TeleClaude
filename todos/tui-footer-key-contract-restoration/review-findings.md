# Review Findings: tui-footer-key-contract-restoration

Review round: 1
Tests: 2418 passed, 106 skipped (0 failures)

## Paradigm-Fit Assessment

1. **Data flow**: Implementation uses established message passing (`post_message` with `RestartSessionsRequest`, `CreateSessionRequest`), existing data models (`ComputerInfo`, `ProjectInfo`, `ComputerDisplayInfo`), and the config patch layer (`telec config patch`). No data layer bypasses. `RestartSessionsRequest` already existed in `messages.py:102` and is properly reused.
2. **Component reuse**: `ComputerHeader` from sessions view is reused (not copy-pasted) in preparation tree. `check_action()` gating pattern followed consistently. `ModalScreen` extended for `NewProjectModal`. `ConfirmModal` reused for restart confirmation.
3. **Pattern consistency**: Overloaded key bindings (`n` for `new_session`/`new_project`, `R` for `restart_session`/`restart_project`/`restart_all`) follow established Textual pattern with `check_action()` gating. Tree building in preparation follows sessions view structure. `_resolve_context_for_cursor()` correctly handles `ComputerHeader` by walking forward to find the first project under it.

## Important

- **Duplicated persistence callback in `action_new_project()`** (`sessions.py:870-908`, `preparation.py:685-725`): The `on_result` callback containing `subprocess.run(["telec", "config", "patch", "--yaml", yaml_patch])` is duplicated verbatim in both views. A shared utility function would eliminate the duplication and reduce maintenance surface. Not a functional defect; both implementations are correct.

## Suggestions

- **Redundant `check_action` branch** (`preparation.py:524-528`): The `if action == "new_project": return True` check is redundant since the fallthrough also returns `True`. The disabled-actions set already excludes `new_project`.

- **YAML string interpolation without escaping** (`sessions.py:885`, `preparation.py:701`): User input (`result.name`, `result.path`, `result.description`) is f-string interpolated into YAML without quoting or escaping. Special YAML characters (`:`, `#`, `{`, `[`) in project names or paths could produce malformed YAML. Risk is low since input is local TUI, not external/untrusted.

- **Fabricated `ComputerInfo` in preparation view** (`preparation.py:200-208`): The prep view constructs `ComputerInfo` with hardcoded values (`status="online"`, `user=""`, `tmux_binary="tmux"`) because it lacks access to real computer metadata. Works for display since `ComputerHeader` currently only reads `name` and `is_local`, but fragile if rendering expands to use other fields.

## Requirements Trace

| Requirement                                  | Status | Evidence                                                                                                          |
| -------------------------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------- |
| Enter on computer -> path-mode session modal | Met    | `action_focus_pane()` routes `ComputerHeader` to `action_new_session(path_mode=True)` (`sessions.py:670`)         |
| R on project -> restart project sessions     | Met    | `action_restart_project()` collects sessions by project_path, shows `ConfirmModal` (`sessions.py:820-849`)        |
| New Project modal with validation            | Met    | `NewProjectModal` validates name uniqueness, path uniqueness, path existence (`modals.py:399-488`)                |
| StartSessionModal path-input mode            | Met    | `path_mode` parameter toggles path input; `~` resolution via `expanduser()`, inline error (`modals.py:289-382`)   |
| Todo tree computer grouping                  | Met    | `_rebuild()` groups by `project.computer`, sorted alphabetically (`preparation.py:187-289`)                       |
| Prep view check_action for computer nodes    | Met    | `ComputerHeader` branch disables todo-specific actions, enables `new_project` and fold (`preparation.py:520-528`) |
| Hidden bindings `1/2/3/4`                    | Met    | App-level bindings have `show=False`, still active                                                                |
| Footer Row 2 globals `q`, `r`, `t`           | Met    | App-level bindings shown by default                                                                               |
| Tests covering key contract                  | Met    | 24 tests in `test_tui_key_contract.py`, updated tests in `test_tui_footer_migration.py`                           |

## Manual Verification Evidence

- TUI cannot be launched in the review environment (requires running daemon). Visual verification deferred to post-merge demo.
- All behavioral contracts verified through unit tests: `check_action()` returns, `_default_footer_action()` returns, modal validation flows, tree structure assertions.
- `_resolve_context_for_cursor()` traced: correctly walks forward from ComputerHeader to find first project, falls back to `self._projects[0]` if no project under computer.

## Why No Critical Issues

1. Paradigm-fit verified: data flow uses message passing and config patch layer; no inline hacks or data layer bypasses.
2. Component reuse verified: `ComputerHeader` reused (not copy-pasted), modal follows `ModalScreen` pattern, tree building follows sessions view structure.
3. Copy-paste check: one duplication found (`action_new_project` callback) rated as Important; no component-level copy-paste.
4. All 9 success criteria from requirements traced to implementations with file:line references.

## Verdict: APPROVE
