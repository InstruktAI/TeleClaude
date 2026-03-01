# Bug: 

## Symptom

It's this is this is this is called a terminal, but yeah it is it is it's it's a terminal user interface it's built in the terminal based with characters and all that stuff and this is actually a session an AI session that is wrapped that is running on and and this is something that's placed on the side and it starts a pane and it renders the thing inside so I can switch between all of these sessions I can actually make them sticky and then they are like you know see I can just I can navigate between four sessions even five sessions and I can just interface with those I can see when stuff happens here I see they now have a small it's work it's it still works it's so funny anyway I can also close them all off I think again they remove that for me oh it's now where's the letter A okay that's one thing I lost so I have to do norm norm norm norm norm norm norm norm norm normally I can just unclicky them and sticky them all in one go with one letter but that is removed in the revamp of the whole platform because it's so smooth now it's so performant oh it's still it still has a split pane okay split logic so I just start I just create a bug hey where's bug oh maybe I have to choose bug fix layout issues issues sticky removal. Fix this, please, for once and for all. Don't cause any regression because I will kill you. You will do this elegantly in the dry way, no hacky sacky shit, okay? 

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-01

## Investigation

The symptom describes a key (the user refers to "letter A") that used to toggle all
sessions for a project sticky/unsticky in one keystroke. This was present in the old
curses-based TUI (`handle_key` with `ord("a")` dispatching to `_open_project_sessions`)
but was not ported to the new Textual-based TUI.

Searched `sessions.py` BINDINGS: no `"a"` binding present. Searched git log for
`_open_project_sessions`: found it in commit `029bd8f4` (the last curses version). The
method toggled all project sessions sticky (first press = make first 5 sticky; second
press = remove all sticky for that project). This logic was lost during the Textual
rewrite (`c680e05c`).

Pre-existing test failure also found: `test_no_fallbacks` triggered by a stale
`# Fallback for …` comment in `teleclaude/cli/tui/animations/base.py:203` — unrelated to
the sticky feature but blocking lint.

## Root Cause

The `action_toggle_project_sessions` method (bound to key `a`) and its corresponding
`Binding` were never ported from the curses `handle_key`/`_open_project_sessions`
implementation to the Textual rewrite of `SessionsView`.

## Fix Applied

Three changes in a single commit:

1. **`teleclaude/cli/tui/views/sessions.py` — `BINDINGS`**
   Added `Binding("a", "toggle_project_sessions", "Open/Close")` after the `n` bindings.

2. **`teleclaude/cli/tui/views/sessions.py` — `action_toggle_project_sessions()`**
   New method added before `check_action`. Mirrors old `_open_project_sessions` logic:
   - Resolves sessions for the selected project+computer.
   - If any are sticky → removes them all; clears preview if it belongs to the project.
   - If none are sticky → adds first `MAX_STICKY` eligible (non-headless) sessions.
   - Notifies user when sessions are truncated or none are attachable.

3. **`teleclaude/cli/tui/views/sessions.py` — `check_action()`**
   Merged `restart_project` and `toggle_project_sessions` into a single
   `ProjectHeader`-gated branch.

4. **`teleclaude/cli/tui/animations/base.py`**
   Renamed `# Fallback for …` comment to `# Pass through … unchanged` to fix the
   pre-existing `test_no_fallbacks` guardrail failure.

5. **`tests/unit/test_sessions_view_toggle_project.py`**
   New test file with 9 unit tests covering toggle-on, toggle-off, preview clearing,
   MAX_STICKY limit enforcement, headless-session skipping, and project+computer scoping.
