# Demo: tui-footer-clickable-agents

## Validation

```bash
# Verify API endpoint exists and responds
curl -s --unix-socket /tmp/teleclaude-api.sock http://localhost/agents/availability | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'claude' in d, 'missing claude'; print('OK: availability endpoint works')"
```

## Guided Presentation

### Step 1: Observe the baseline

Open the TUI with `telec`. Look at the bottom status bar. You should see three agent pills:

- `claude ✔` (available, bright)
- `gemini ✔` or `gemini ~` (depending on current state)
- `codex ✔` or similar

Note the current state of each agent.

### Step 2: Click to degrade

Click on the `claude` pill in the footer. Observe:

- The pill changes to `claude ~` (degraded indicator)
- The color dims to the muted palette
- Claude is now excluded from automatic dispatch selection but can still be manually chosen

### Step 3: Click to disable

Click on the `claude ~` pill again. Observe:

- The pill changes to `claude ✘(60m)` (unavailable with countdown)
- The color remains muted
- Claude is now fully unavailable for dispatch

### Step 4: Click to restore

Click on the `claude ✘(...)` pill again. Observe:

- The pill returns to `claude ✔` (available, bright)
- Claude is back in the dispatch pool

### Step 5: Verify persistence

After cycling claude back to available, refresh the TUI (press `r`). Confirm the state persists — it round-tripped through the daemon API, not just local widget state.
