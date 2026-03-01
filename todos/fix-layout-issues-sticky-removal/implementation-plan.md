# Implementation Plan: fix-layout-issues-sticky-removal

## Overview
Restore the "a" key binding for batch-toggling project sessions sticky/unsticky mode in the Textual-based TUI, which was lost during the Textual rewrite.

## Problem Statement
The old curses-based TUI had an `"a"` key binding that would toggle all sessions for a selected project sticky (up to MAX_STICKY limit) or remove all sticky sessions if any were already sticky. This functionality was not ported to the new Textual-based SessionsView.

## Solution Architecture

### Core Changes
1. **Restore the "a" key binding in SessionsView**
   - Add `Binding("a", "toggle_project_sessions", "Open/Close")` to BINDINGS list
   - Bind to a new action method `action_toggle_project_sessions()`

2. **Implement toggle logic**
   - Detect if any sessions for the selected project are already sticky
   - If sticky sessions exist → remove all sticky sessions for that project
   - If no sticky sessions exist → make first MAX_STICKY eligible sessions sticky
   - Clear preview state if it belongs to the toggled project
   - Provide user feedback for truncation or lack of attachable sessions

3. **Add comprehensive unit tests**
   - Test toggle-on behavior (sticky sessions)
   - Test toggle-off behavior (unsticky sessions)
   - Test preview clearing
   - Test MAX_STICKY limit enforcement
   - Test headless session skipping
   - Test proper project+computer scoping

### Files Modified
1. `teleclaude/cli/tui/views/sessions.py`
   - BINDINGS list
   - action_toggle_project_sessions() method
   - check_action() method refactoring

2. `teleclaude/cli/tui/animations/base.py`
   - Comment cleanup (fallback comment)

3. Pre-existing lint fixes across multiple files
   - test_animations.py
   - discord_adapter.py
   - pyproject.toml
   - animation_engine.py
   - animations/base.py
   - animations/creative.py
   - animations/general.py
   - app.py
   - pixel_mapping.py
   - widgets/banner.py
   - widgets/box_tab_bar.py
   - test_agent_coordinator.py
   - test_tts_fallback_saturation.py

4. `tests/unit/test_sessions_view_toggle_project.py` (new)
   - 9 unit tests for toggle functionality

## Implementation Details

### action_toggle_project_sessions() Logic
```
1. Get selected row (ProjectHeader or SessionsHeader)
2. If ProjectHeader is selected:
   a. Resolve all sessions for project+computer
   b. Check if any are currently sticky
   c. If yes → remove sticky from all, clear preview if needed
   d. If no → make first MAX_STICKY eligible sessions sticky
   e. Provide feedback (truncation warning if applicable)
3. Otherwise → do nothing (silently ignore)
```

### Edge Cases Handled
- Headless sessions are not made sticky
- Existing sticky sessions in other projects remain unchanged
- Preview state is cleared only if it belongs to toggled project
- User receives feedback when sessions are truncated (more than MAX_STICKY available)
- User receives feedback when no attachable (non-headless) sessions exist

## Success Criteria
- ✓ "a" key restores all 5 sessions to sticky (or fewer if less available)
- ✓ Second press of "a" removes all sticky sessions for that project
- ✓ Tests pass: 2534 passed, 106 skipped
- ✓ Lint passes: all checks passed, 0 errors
- ✓ No regressions in unrelated functionality

## Risks & Mitigations
| Risk | Mitigation |
|------|-----------|
| Project scope confusion | Implementation checks project+computer pair, not just project |
| Headless session handling | Explicitly filter headless sessions from toggle |
| Preview state corruption | Clear preview only if it belongs to toggled project |
| MAX_STICKY enforcement | Confirm limit is respected when toggling on |
