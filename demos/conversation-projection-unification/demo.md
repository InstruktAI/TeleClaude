# Demo: conversation-projection-unification

## Medium

Web interface (Next.js frontend) + API endpoints + CLI verification.

## What the user observes

### Before (current state)

1. Open web chat for an active agent session.
2. The live SSE stream shows internal tool blocks (tool_use, tool_result) as generic tool UI elements — these are internal transcript entries that should not be visible.
3. Navigate to the same session's history view. Tool blocks are hidden — the history path filters them out.
4. **Visible inconsistency**: live stream shows tool noise, history does not. Same session, different projections.

### After (unified projection)

1. Open web chat for an active agent session.
2. The live SSE stream shows only text and thinking content — internal tool blocks are suppressed.
3. Navigate to the same session's history view. Same content is visible — text and thinking, no tool noise.
4. **Parity achieved**: live stream and history show identical conversation content from the same transcript chain.
5. If a tool is explicitly allowlisted as user-visible (e.g., a widget tool), it appears in both views consistently.

## Validation commands

```bash
# 1. Run the projection unit tests
make test ARGS="-k projection"

# 2. Run the web parity tests specifically
make test ARGS="-k test_web_parity"

# 3. Run the full regression suite
make test

# 4. Run linting
make lint

# 5. Verify no adapter files were modified
git diff --name-only | grep -v "teleclaude/adapters/" || echo "No adapter changes (correct)"

# 6. Verify the new projection package exists
ls -la teleclaude/output_projection/

# 7. Manual verification: start a session, open web chat, confirm no tool block leakage
# Compare live SSE output with history API output for the same session
```

## Key scenarios to demonstrate

1. **Tool suppression**: Agent uses internal tools (Read, Write, Bash) — none appear in web chat.
2. **Allowlisted tool visibility**: If a tool is marked user-visible, it appears in both live and history views.
3. **Thinking parity**: Thinking blocks appear consistently (or not) based on the projection policy, not per-path logic.
4. **Threaded output unchanged**: Threaded mode output in adapters behaves identically to before.
5. **Poller output unchanged**: Standard tmux-live output to adapters behaves identically to before.
