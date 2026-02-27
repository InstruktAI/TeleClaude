# Demo: tui-footer-key-contract-restoration

## Validation

```bash
# Verify tests pass for key contract
make test ARGS="-k tui_footer or tui_key_contract or check_action"
```

```bash
# Verify TUI starts without errors
timeout 5 telec 2>&1 || true
```

## Guided Presentation

**Medium:** TeleClaude TUI (terminal)

### Step 1: Sessions tab — Computer node key contract

1. Launch `telec` and navigate to the Sessions tab (key `1`).
2. Move cursor to a **Computer** header node.
3. **Observe:** Footer Row 1 shows `Enter` (New Session), `n` (New Project), `R` (Restart All), `+/-` (Collapse/Expand).
4. Press `Enter`. **Observe:** StartSessionModal opens with a path input field.
5. Type `~/nonexistent-path` and press Enter. **Observe:** Modal stays open with inline error "Path does not exist."
6. Press Escape to dismiss.
7. Press `n`. **Observe:** NewProjectModal opens with name, description, path fields.

### Step 2: Sessions tab — Project node key contract

1. Move cursor to a **Project** header node.
2. **Observe:** Footer Row 1 shows `Enter` (New Session), `R` (Restart All), `+/-`.
3. Press `R`. **Observe:** Confirm dialog for restarting all sessions in that project.

### Step 3: Sessions tab — Session node key contract

1. Move cursor to a **Session** row.
2. **Observe:** Footer Row 1 shows `Space` (Preview), `Enter` (Focus), `k` (Kill), `R` (Restart).
3. Press `Space` once. **Observe:** Preview pane opens. Press `Space` again within 0.65s. **Observe:** Sticky mode.

### Step 4: Todo tab — Computer grouping restored

1. Switch to the Todo tab (key `2`).
2. **Observe:** Tree shows Computer → Project → Todo hierarchy (not flat Project → Todo).
3. Move cursor to a **Computer** header. **Observe:** Footer shows `n` (New Project), `+/-`.
4. Move cursor to a **Project** header. **Observe:** Footer shows `t`/`Enter` (New Todo), `b` (New Bug), `+/-`.

### Step 5: Todo tab — Todo node actions

1. Move cursor to a **Todo** row.
2. **Observe:** Footer shows `t` (New Todo), `p` (Prepare), `s` (Start), `R` (Remove).
3. Press `p`. **Observe:** StartSessionModal opens with `/next-prepare <slug>` prefilled.
4. Press Escape. Press `s`. **Observe:** StartSessionModal opens with `/next-work <slug>` prefilled.

### Step 6: Global row consistency

1. On any tab, **observe** Footer Row 2: `q` (Quit), `r` (Refresh), `t` (Theme) — dimmed.
2. **Observe** Footer Row 3: agent pills, `s` (Speech toggle), `a` (Animation toggle).
3. Press `3`. **Observe:** Tab switches to Jobs (hidden key works, not shown in footer).
