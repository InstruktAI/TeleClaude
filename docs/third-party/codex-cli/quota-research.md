---
description: Codex CLI quota and usage retrieval research for TeleClaude dispatch decisions.
---

# Codex CLI Quota Research

## Overview

This note records local research into reading Codex CLI quota state for dispatch decisions. The future-agent question is: how can TeleClaude determine Codex five-hour and weekly allowance state without spending an unnecessary model turn?

## Provenance

These findings come from local CLI and session-log research performed on 2026-06-26. They are not vendor-documented in the public Codex CLI command docs reviewed for this repository, and the useful behavior is treated as an observed local runtime contract until upstream documentation says otherwise.

## Findings

- `codex exec '/status'` does not execute the TUI `/status` slash command. It sends `/status` as ordinary model input and consumes a model turn.
- Codex session logs contain structured quota data in `event_msg` records where `payload.type == "token_count"`.
- The real log layout is nested by date: `~/.codex/sessions/YYYY/MM/DD/*.jsonl`.
- The quota data lives at `payload.rate_limits`.
- `payload.rate_limits.primary` matched the five-hour window in local testing:
  - `window_minutes: 300`
  - `used_percent`
  - `resets_at` as a Unix epoch timestamp
- `payload.rate_limits.secondary` matched the weekly window in local testing:
  - `window_minutes: 10080`
  - `used_percent`
  - `resets_at` as a Unix epoch timestamp
- The same values matched the TUI `/status` display: `100 - used_percent` equals the displayed percent left.
- A controlled TUI fallback can refresh the value without a model turn by starting Codex in tmux, sending `/status`, capturing the pane, and ending the session.

## Tested passive extraction

```bash
latest=$(
  find ~/.codex/sessions -type f -name '*.jsonl' -print0 \
    | xargs -0 stat -f '%m %N' \
    | sort -nr \
    | head -1 \
    | cut -d' ' -f2-
)

jq -c '
  select(.type == "event_msg" and .payload.type == "token_count")
  | {timestamp, rate_limits: .payload.rate_limits}
' "$latest" | tail -1
```

## Tested TUI fallback

```bash
tmux new-session -d -s usage_probe_codex -x 120 -y 40 \
  'codex --no-alt-screen --ask-for-approval never --sandbox read-only'
tmux send-keys -t usage_probe_codex '/status' Enter
tmux capture-pane -pt usage_probe_codex -S -80
tmux kill-session -t usage_probe_codex
```

## Recommended collector shape

Prefer passive structured extraction from the latest session log when the newest `token_count` event is fresh enough for dispatch decisions. If no fresh structured record exists, run the controlled TUI fallback and let an intelligent runner interpret the pane output into normalized state.

## Caveats

- Do not `cat` full Codex JSONL logs in routine probes; they contain transcripts and prompt content. Filter for `payload.type == "token_count"`.
- `codex exec` should not be used to query `/status`, because it spends a model turn and only creates quota evidence as a side effect.
- If primary/secondary window lengths change, classify by `window_minutes` rather than by field name alone.
