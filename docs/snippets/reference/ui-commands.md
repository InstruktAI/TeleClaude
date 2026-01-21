---
id: teleclaude/reference/ui-commands
type: reference
scope: project
description: Telegram slash commands registered from UiCommands.
requires: []
---

## What it is

- Canonical list of Telegram slash commands exposed by `UiCommands`.

## Canonical fields

- Session lifecycle: `/new_session`.
- Agent control: `/agent_restart`, `/agent_resume`, `/claude`, `/gemini`, `/codex`, `/claude_plan`.
- Help: `/help`.
- Signals: `/cancel`, `/cancel2x`, `/kill`.
- Keys: `/tab`, `/shift_tab`, `/enter`, `/escape`, `/escape2x`, `/backspace`, `/key_up`, `/key_down`, `/key_left`, `/key_right`, `/ctrl`.

## Allowed values

- Command names must match `UiCommands` registrations.

## Known caveats

- Command availability depends on the adapter’s registration and master-bot policy.
