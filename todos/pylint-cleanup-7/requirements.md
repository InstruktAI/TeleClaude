<!-- from-main: inline work delivered under human supervision -->

# Requirements: pylint-cleanup-7

## Objective

Fix ALL pylint violations in the following paths:
teleclaude/api teleclaude/events teleclaude/channels teleclaude/transport teleclaude/hooks

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
