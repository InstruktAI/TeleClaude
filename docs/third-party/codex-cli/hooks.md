---
description: Codex Hooks
id: third-party/codex-cli/hooks
scope: project
type: third-party
---

# Codex Hooks

## Overview

Codex uses native hooks from `~/.codex/hooks.json`, with the runtime feature
enabled by `~/.codex/config.toml`:

```toml
[features]
codex_hooks = true
```

TeleClaude currently manages this native Codex subset:

- `SessionStart`
- `UserPromptSubmit`
- `Stop`

`tool_use` is synthesized from terminal-output polling (see polling_coordinator).

## Input shape we care about

Codex hook commands receive JSON on stdin with common fields plus event-specific
fields.

Shared fields TeleClaude relies on:

- `hook_event_name` — native Codex hook event name
- `session_id` — native Codex session id
- `transcript_path` — native transcript path when available
- `cwd` — working directory

`UserPromptSubmit` adds:

- `turn_id` — active Codex turn id
- `prompt` — user prompt about to be sent

`Stop` adds:

- `turn_id` — active Codex turn id
- `stop_hook_active` — whether this turn was already continued by `Stop`
- `last_assistant_message` — latest assistant text, if available

## Stdout behavior

`UserPromptSubmit`:

- `matcher` is not currently used
- plain stdout text is added as extra developer context
- JSON stdout may include `hookSpecificOutput.additionalContext`
- JSON stdout may also return `decision: "block"` with a reason

`Stop`:

- `matcher` is not currently used
- plain stdout is invalid
- stdout must be JSON when exiting `0`
- `decision: "block"` does not reject the turn; it tells Codex to continue
  using the provided reason as the continuation prompt

## TeleClaude mapping

- `SessionStart` → `session_start`
- `UserPromptSubmit` → `user_prompt_submit`
- `Stop` → `agent_stop`

Payload normalization used by the adapter:

- `prompt` stays `prompt`
- `last_assistant_message` → `message`

## TeleClaude notes

- TeleClaude receiver commands do not need a positional event argument for Codex.
- The receiver reads `hook_event_name` from stdin and maps it through the shared adapter path.
- TeleClaude uses native `Stop` continuation JSON for checkpointing.
- TeleClaude does not currently emit Codex `UserPromptSubmit` additional-context output.

## Source

- https://developers.openai.com/codex/hooks
