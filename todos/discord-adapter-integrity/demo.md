# Demo: discord-adapter-integrity

## Validation

```bash
# Phase 1: Infrastructure validation — stale IDs are re-provisioned
# (Manual: delete a Discord forum, restart daemon, verify it re-creates)
make status
```

```bash
# Phase 3: Text delivery — verify poller triggers incremental output for threaded sessions
make test -- -k "threaded_output" --no-header -q
```

```bash
# Lint clean
make lint
```

## Guided Presentation

### Step 1: Infrastructure hardening

1. Show `_ensure_discord_infrastructure` with the new `_validate_channel_id` helper.
2. Explain: every stored channel ID is now verified via Discord API on startup. Stale IDs are cleared and re-provisioned automatically. No more silent 404s.

### Step 2: Per-computer project categories

1. Show the Discord guild sidebar — observe "Projects - MozBook" and "Projects - mozmini" as separate categories.
2. Show config.yml — each computer has its own category key (`categories.projects_mozbook`).
3. Start a session on each computer — observe the session thread appears in the correct computer-specific project forum.

### Step 3: Text delivery between tool calls

1. Start a Claude session that will produce text between tool calls (e.g., a research task with reasoning).
2. Observe the Discord thread: text output appears within ~2s of being written to the transcript, not delayed until the next tool_use or agent_stop.
3. Compare with TUI output — both should show the same content with minimal delay.
4. Repeat with a Gemini session on Telegram — same continuous delivery.

### Step 4: Verify no regressions

1. Claude on Telegram (non-threaded): verify poller still delivers raw tmux output as before.
2. Hook-triggered events (tool_use, tool_done, agent_stop): verify these still fire and the digest dedup prevents double delivery when both hook and poller trigger within the same second.
