<!-- from-main: inline work delivered under human supervision -->
# Requirements: pylint-cleanup-5

## Objective

Fix ALL pylint violations in the following paths:
teleclaude/cli/tui/app.py teleclaude/cli/tui/app_actions.py teleclaude/cli/tui/app_ws.py teleclaude/cli/tui/pane_bridge.py teleclaude/cli/tui/pane_manager.py teleclaude/cli/tui/pane_layout.py teleclaude/cli/tui/theme.py teleclaude/cli/tui/controller.py teleclaude/cli/tui/state.py teleclaude/cli/tui/messages.py teleclaude/cli/tui/pane_theming.py teleclaude/cli/tui/animation_engine.py teleclaude/cli/tui/base.py teleclaude/cli/telec teleclaude/cli/session_auth.py teleclaude/cli/api_client.py

## Instructions

1. Run `pylint <paths>` to see all violations
2. Fix every violation. Common fixes:
   - `import-outside-toplevel`: Move imports to module top level
   - `broad-exception-caught`: Catch specific exceptions
   - `missing-function-docstring`: Add docstrings
   - `unused-argument`: Prefix with underscore or remove
   - `too-many-locals/arguments/branches`: Refactor to reduce complexity
   - `line-too-long`: Wrap lines to 120 chars
   - `invalid-name`: Fix naming conventions
   - `protected-access`: Use public API or add accessor
   - `useless-import-alias`: Remove alias
3. After fixing, run `pylint <paths>` again — must exit 0 with no violations
4. Run `pytest` to ensure no regressions
5. Commit per-directory with message: `fix(lint): resolve pylint violations in <dir>`

## Acceptance Criteria

- `pylint <paths>` exits with code 0
- All existing tests pass
- No behavioral changes — lint fixes only
