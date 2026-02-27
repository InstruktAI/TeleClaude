# Demo: tui-footer-polish

## Validation

```bash
# Verify tests pass
make test
```

```bash
# Verify lint passes
make lint
```

## Guided Presentation

### Step 1: Modal Sizing

1. Open the TUI (`telec`).
2. Navigate to Preparation view (press `2`).
3. Select a Computer node and press `n` to open NewProjectModal.
4. **Observe:** Modal is compact and centered — fits its 4 fields, not full-screen.
5. Press Escape to close.

### Step 2: Key Contrast

1. Switch to light mode (OS appearance or theme cycling).
2. Navigate to a todo node to populate Row 1 with context bindings.
3. **Observe:** Key letters (`n`, `b`, `p`, `s`, `R`) render dark/high-contrast. Labels render in visible gray.
4. Switch to dark mode.
5. **Observe:** Key letters render bright/white. Labels render in dimmed gray.

### Step 3: Plain Global Keys

1. Look at Row 2 (the dimmed global row).
2. **Observe:** Shows `q Quit  r Refresh  t Cycle Theme` — plain lowercase letters, no unicode symbols (`⏻`, `↻`, `◑` are gone).

### Step 4: Toggle Bindings

1. Press `a`.
2. **Observe:** Animation mode cycles — Row 3 icon changes (✨ → 🎉 → 🚫 → ✨).
3. Press `s` (or `v` if fallback was used).
4. **Observe:** TTS toggles — Row 3 icon changes (🔊 ↔ 🔇).
5. Verify both `a` and TTS key appear in Row 2 hints.

### Step 5: Roadmap Reordering

1. Navigate to Preparation view (press `2`).
2. Select a root todo row (not a sub-item, file, or header).
3. **Observe:** Row 1 shows `Shift+↑` and `Shift+↓` hints.
4. Press `Shift+Down`.
5. **Observe:** The todo moves down one position in the tree. Roadmap order is updated.
6. Press `Shift+Up`.
7. **Observe:** The todo moves back up.
8. Select a file row or header node.
9. **Observe:** `Shift+↑`/`Shift+↓` hints disappear from Row 1 (gated by check_action).
