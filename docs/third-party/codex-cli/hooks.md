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
hooks = true
```

The `hooks` feature is `Stage::Stable` with `default_enabled = true` in codex
0.129+, so the explicit flag is belt-and-suspenders.

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

## Trust gate (Codex 0.129+)

Codex 0.129 added a per-hook trust requirement (PR
[`openai/codex#20321`](https://github.com/openai/codex/pull/20321)). Hooks
discovered from `~/.codex/hooks.json` are `User`-layer (unmanaged) and stay
out of the runnable handler set until `~/.codex/config.toml` carries a matching
`trusted_hash` for each handler. Without that entry codex silently drops the
handler — no log, no warning beyond a one-line startup banner.

Persisted shape:

```toml
[hooks.state."<key>"]
trusted_hash = "sha256:<hex>"
enabled = true   # optional; user toggle from /hooks
```

Where `<key>` is `{abs_hooks_json_path}:{event_label}:{group_index}:{handler_index}`
and `event_label` is the snake-cased name (`session_start`, `user_prompt_submit`,
`stop`, …).

`trusted_hash` is a SHA-256 of the canonical JSON representation of the
normalized hook identity. Codex's algorithm
(`codex-rs/hooks/src/engine/discovery.rs::command_hook_hash` +
`codex-rs/config/src/fingerprint.rs::version_for_toml`):

1. Build `{ event_name, matcher, hooks: [normalized_handler] }`.
2. Force `matcher` to `None` for `UserPromptSubmit` and `Stop`. Keep the
   configured matcher for `SessionStart` and the tool/compact events.
3. Normalize `timeout` to `Some(timeout_sec.unwrap_or(600).max(1))`.
4. Convert struct → TOML value → JSON value. None-typed fields drop out.
5. Recursively sort object keys (canonical JSON), serialize compactly, hash,
   prefix with `sha256:`.

`telec init` writes these entries deterministically via
`teleclaude.install.codex_hook_trust`, so a fresh codex session picks up the
hooks without forcing the operator through the `/hooks` TUI. The installer
overwrites `trusted_hash` on every run (it must track the current command) but
preserves any user-set `enabled = false`.

## Source

- https://developers.openai.com/codex/hooks
- https://github.com/openai/codex/pull/20321
