# Demo: fix-sticky-removal-layout-issues

## Validation

```bash
# Unit tests cover the un-sticky → preview transition
cd /Users/Morriz/Workspace/InstruktAI/TeleClaude && make test-unit -- tests/unit/test_tui_state.py -v
```

```bash
# Full lint check
cd /Users/Morriz/Workspace/InstruktAI/TeleClaude && make lint
```

## Guided Presentation

### Medium

TUI (Python Textual app running in terminal via `telec`).

### Step 1: Setup — Create two sticky sessions

1. Open the TUI: `telec`
2. Start or select two sessions and double-press each to make them sticky.
3. Observe: two sticky panes appear alongside the session list. Note the pane count.

### Step 2: Un-sticky one session

1. Double-press one of the sticky sessions.
2. **Observe:** The session is removed from the sticky list but immediately becomes the active preview.
3. **Observe:** The total pane slot count does not change — the sticky slot seamlessly becomes a preview slot.
4. **Observe:** No layout flicker or full pane rebuild occurs.

### Step 3: Un-sticky with an existing preview

1. Start with one sticky session and one preview session (different sessions).
2. Double-press the sticky session.
3. **Observe:** The previously active preview is dismissed. The un-stickied session replaces it as preview.
4. **Observe:** Layout remains stable — same slot count throughout.

### Step 4: Un-sticky the last sticky with no prior preview

1. Start with one sticky session and no active preview.
2. Double-press the sticky session.
3. **Observe:** The session becomes the active preview. Layout slot count stays the same.

### Why it matters

The un-sticky → preview transition preserves the user's focus on the session they just interacted with. Without this fix, un-stickying causes the pane to vanish entirely, triggering a jarring layout rebuild. The fix ensures smooth, predictable behavior matching the design spec.
