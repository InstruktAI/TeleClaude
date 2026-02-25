# Review Findings: tui-state-persistence

## Paradigm-Fit Assessment

- Data flow: uses the established TUI-local persistence boundary (`state_store` + widget messages) and does not bypass core layers.
- Component reuse: extends existing `SessionsView`, `PreparationView`, and footer patterns instead of introducing duplicate flows.
- Pattern consistency: event-driven `StateChanged` persistence matches adjacent Textual message patterns.

## Critical

- None.

## Important

1. Default pane-theming mode regresses to `off` when no persisted state exists, instead of honoring the configured default (`full`/`agent_plus`).
   - Evidence:
     - Empty state returns `status_bar: {}` on missing file: `teleclaude/cli/tui/state_store.py:80` and `teleclaude/cli/tui/state_store.py:108`.
     - Footer default is `pane_theming_mode = "off"`: `teleclaude/cli/tui/widgets/telec_footer.py:35`.
     - Mount applies that value directly: `teleclaude/cli/tui/app.py:246`.
     - Config default remains `pane_theming_mode: full`: `teleclaude/config/__init__.py:179`.
   - Impact: first-run users (or users after deleting `~/.teleclaude/tui_state.json`) start with less theming than configured before this change.
   - Suggested fix: seed missing `status_bar.pane_theming_mode` from config/canonical default (`agent_plus`) before applying theme override.

## Suggestions

1. Manual verification gap for interactive behavior remains in this review environment.
   - Not directly exercised here: SIGUSR2 persistence flows and live TUI metadata refresh behavior.
   - Automated evidence gathered: targeted unit/integration tests for touched files passed, and `make lint` passed.

## Verdict

REQUEST CHANGES

## Fixes Applied

1. Important: Default pane-theming mode regressed to `off` when persisted state was missing.
   - Fix: `state_store` now seeds/normalizes `status_bar` defaults using canonical config-backed pane theming mode, and regression tests cover missing-file and missing-key paths.
   - Commit: `8d06852f79c3463a908bfc3c386d0ce0c2345351`
