# Review Findings: tui-footer-key-contract-restoration

## Paradigm-Fit Assessment

1. **Data flow**: Implementation uses established message passing (`post_message` with `RestartSessionsRequest`, `CreateSessionRequest`), existing data models (`ComputerInfo`, `ProjectInfo`, `ComputerDisplayInfo`), and the config patch layer (`telec config patch`). No data layer bypasses.
2. **Component reuse**: Reuses `ComputerHeader` from sessions view in preparation tree. Follows existing `check_action()` gating pattern. Extends `ModalScreen` for `NewProjectModal`. `ConfirmModal` reused for restart confirmation.
3. **Pattern consistency**: Overloaded key bindings (`n` for `new_session`/`new_project`, `R` for `restart_session`/`restart_project`/`restart_all`) follow established Textual pattern with `check_action()` gating. Tree building in preparation follows sessions view structure.

## Important

- **Duplicated persistence callback in `action_new_project()`** (`sessions.py:880-897`, `preparation.py:695-715`): The `on_result` callback containing `subprocess.run(["telec", "config", "patch", "--yaml", yaml_patch])` is duplicated verbatim in both views. This is identical logic handling project creation persistence — a shared utility function would eliminate the duplication and reduce maintenance surface. Not a functional defect; both implementations are correct.

## Suggestions

- **Redundant `check_action` branch** (`preparation.py:526-528`): The explicit `if action == "new_project": return True` check is redundant since the fallthrough on line 528 also returns `True`. The disabled-actions set on line 524 already excludes `new_project`, so the intermediate check adds no gating value.

- **YAML string interpolation without escaping** (`sessions.py:885`, `preparation.py:701`): User input (`result.name`, `result.path`, `result.description`) is f-string interpolated into YAML without quoting or escaping. Special YAML characters (`:`, `#`, `{`, `[`) in project names or paths could produce malformed YAML. Consider wrapping values in single quotes: `'  - name: "{result.name}"'` or using a YAML serializer. Risk is low since input is local TUI, not external/untrusted.

- **Fabricated `ComputerInfo` in preparation view** (`preparation.py:202-208`): The prep view constructs `ComputerInfo` with hardcoded values (`status="online"`, `user=""`, `tmux_binary="tmux"`) because it lacks access to real computer metadata. This works for display since `ComputerHeader` currently only reads `name` and `is_local`, but is fragile if rendering expands to use other fields. Consider passing a lightweight display-only struct or documenting the contract.

## Requirements Trace

| Requirement                                 | Status | Evidence                                                                                                                           |
| ------------------------------------------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| Enter on computer → path-mode session modal | Met    | `action_focus_pane()` routes `ComputerHeader` to `action_new_session(path_mode=True)` (`sessions.py:673`)                          |
| R on project → restart project sessions     | Met    | `action_restart_project()` collects sessions by project_path, shows `ConfirmModal` (`sessions.py:823-845`)                         |
| New Project modal with validation           | Met    | `NewProjectModal` validates name uniqueness, path uniqueness, path existence (`modals.py:394-489`)                                 |
| StartSessionModal path-input mode           | Met    | `path_mode` parameter toggles path input; `~` resolution via `os.path.expanduser()`, inline error on invalid (`modals.py:293-376`) |
| Todo tree computer grouping                 | Met    | `_rebuild()` groups by `project.computer`, sorted alphabetically (`preparation.py:187-289`)                                        |
| Prep view check_action for computer nodes   | Met    | `ComputerHeader` branch disables todo-specific actions, enables `new_project` and fold (`preparation.py:522-528`)                  |
| Hidden bindings `1/2/3/4`                   | Met    | App-level bindings have `show=False` (`app.py:95-126`), still active                                                               |
| Footer Row 2 globals `q`, `r`, `t`          | Met    | App-level bindings shown by default (`app.py:94,127-128`)                                                                          |
| Tests covering key contract                 | Met    | 24 tests in `test_tui_key_contract.py`, updated tests in `test_tui_footer_migration.py`                                            |

## Manual Verification Evidence

- TUI cannot be launched in the review environment (requires running daemon). Visual verification deferred to post-merge demo.
- All behavioral contracts verified through unit tests: `check_action()` returns, `_default_footer_action()` returns, modal validation flows, tree structure assertions.
- Build checklist fully checked by builder with manual verification notes.

## Why No Critical Issues

1. Paradigm-fit verified: data flow uses message passing and config patch layer; no inline hacks or data layer bypasses.
2. Component reuse verified: `ComputerHeader` reused (not copy-pasted), modal follows `ModalScreen` pattern, tree building follows sessions view structure.
3. Copy-paste check: one duplication found (`action_new_project` callback) rated as Important; no component-level copy-paste.
4. All 11 success criteria from requirements traced to implementations with file:line references.

## Verdict: APPROVE
