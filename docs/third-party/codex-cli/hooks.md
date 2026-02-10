# Codex CLI Hooks

## Overview

Codex CLI supports a single hook event via the `notify` command.

## Hook events

| Event               | When It Fires                | Common Use Cases            |
| ------------------- | ---------------------------- | --------------------------- |
| agent-turn-complete | When agent finishes its turn | Review output, update state |

## Hook input contract (selected fields we use)

- `thread-id` (string) — native session ID
- `input-messages` (list of strings) — contains user prompts for the turn
- `last-assistant-message` (string) — agent response

## TeleClaude adapter mapping

Mapping rules:

- `agent-turn-complete` → `event_type = "stop"`
  - Requires `data.thread-id` (native session id).
  - Extracts the last element of `data.input-messages` as `prompt` to update `last_message_sent` in the database.

## Sources

- https://developers.openai.com/codex/config-reference
- https://developers.openai.com/codex/cli/reference
