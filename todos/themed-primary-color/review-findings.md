# Review Findings: themed-primary-color

## Review Scope

Files changed (vs main):

- `teleclaude/cli/tui/theme.py` — Theme objects moved here + agent-variant themes added
- `teleclaude/cli/tui/app.py` — Theme registration, startup/cycle theme switching
- `teleclaude/cli/editor.py` — Theme registration + `--theme` CLI flag via argparse
- `teleclaude/cli/tui/views/preparation.py` — Theme flag passed to editor subprocess

Verified: `make lint` passes (ruff format, ruff check, pyright — 0 errors).

## Critical

(none)

## Important

1. **Stream-of-consciousness comments in `app.py:113-118`** — The comment block reads like
   debug notes ("We don't have settings loaded yet...", "Actually config is a global singleton...",
   "Wait, config.ui.pane_theming_mode is available if config is loaded"). Per code quality policy,
   comments describe the present, not the thought process. Replace with a concise 1-liner like
   `# Select initial theme from persisted pane theming level`.

## Suggestions

1. **`import curses` in `theme.py`** added solely for legacy stubs returning `curses.A_BOLD`.
   Since these are placeholder stubs, returning `0` (already done for other stubs) avoids
   pulling in curses at module scope. Low priority — cosmetic.

2. **Underscore-prefixed theme objects** (`_TELECLAUDE_DARK_THEME` etc.) are imported cross-module
   by `app.py` and `editor.py`. The underscore convention signals "private" but these are part of
   the module's public API. Consider dropping the prefix. Low priority — naming convention only.

3. **Incomplete legacy stubs in `preparation.py`** — `PrepFileDisplayInfo`, `PrepFileNode`,
   `PrepProjectDisplayInfo`, `PrepProjectNode` are still missing (needed by
   `test_tui_preparation_view.py`). Note: these were ALSO missing on main before this branch,
   so this is pre-existing debt, not a regression. The branch partially improved the situation by
   adding 4 of the 8 required stubs.

4. **`get_system_dark_mode` re-export** in `app.py` with `# noqa: F401` exists to support test
   monkeypatching at `teleclaude.cli.tui.app.get_system_dark_mode`. The tests also monkeypatch
   `get_current_mode` which is NOT re-exported — but this is pre-existing on main (test was
   already broken). Not a regression.

## Pre-existing Issues (not attributed to this branch)

- `test_tui_app.py::TestTelecAppWebSocketEvents::test_theme_drift_*` — fail on main too
  (missing `get_current_mode` re-export)
- `test_tui_preparation_view.py` — import error on main too (missing stubs)
- `test_preparation_view.py` — `Widget.__init__()` API mismatch on main too

## Verdict: APPROVE

The core feature implementation is solid:

- Four Textual themes correctly defined (2 peaceful + 2 agent-variant)
- Agent themes share variables via `.copy()` with correct warm `primary`/`secondary`
- Theme switching on carousel cycle correctly maps levels 0,2→neutral, 1,3,4→warm
- Initial theme respects persisted pane theming mode at startup
- Editor subprocess receives `--theme` flag; argparse migration is cleaner than manual sys.argv
- No circular imports; theme objects live in canonical `theme.py` location
- Lint, type checking, and formatting all pass
- No regressions — all test failures verified as pre-existing on main
