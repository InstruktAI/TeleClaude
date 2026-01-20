---
id: guide/troubleshooting
type: guide
scope: global
description: Diagnostic steps for common TeleClaude operational issues.
---

# Troubleshooting Guide

## Step 1: Health Check
Run `make status` to see if the daemon is running and how long it has been up.

## Step 2: Log Inspection
Use the logging tool to see recent errors:
```bash
instrukt-ai-logs teleclaude --since 30m
```
Common grep targets: `ERROR`, `mcp-server`, `telegram-adapter`.

## Step 3: Adapter Verification
- **Telegram**: Check if the bot responds to `/help` in the General topic.
- **MCP**: Check if `/tmp/teleclaude.sock` exists. Run `bin/mcp-wrapper.py` manually to test stdio connectivity.
- **Redis**: Use `redis-cli ping` to verify transport availability.

## Step 4: Session Recovery
If a session is stuck:
1. Try `/cancel` to send SIGINT.
2. Try `/resize large` to force a redraw.
3. If tmux is dead, `/close-session` and start a new one.

## Step 5: Clean State
If code changes cause loops:
1. `make stop`
2. `rm teleclaude.db` (WARNING: This wipes all session history!)
3. `make start`