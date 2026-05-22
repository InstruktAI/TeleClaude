---
id: 'project/spec/feature/integration/agent-cli-hook-reception'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Subprocess receiver invoked by agent CLIs (Claude, Codex, Gemini) that parses a hook payload, resolves a TeleClaude session, and enqueues the event for daemon processing.'
---

# Agent CLI Hook Reception — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

The `telec-hook` subprocess that an agent CLI invokes for every hook event it
emits (`session_start`, `user_prompt_submit`, `tool_use`, `agent_stop`,
`agent_error`, plus event-name variants per agent). The receiver reads a JSON
payload from stdin, selects a per-agent adapter (Claude / Codex / Gemini) to
normalize agent-specific field names, maps the raw event name to a canonical
`AgentHookEventType`, resolves or refreshes a TeleClaude session identifier
from the agent's native session id, and enqueues the event into a per-session
SQLite outbox. The receiver also emits stdout "additional context" on
`agent_session_start` and, on `agent_stop`, may emit an adapter-formatted
checkpoint-block response that the agent CLI interprets as a blocking
instruction.

In v1 this code lives under `teleclaude/hooks/receiver/` even though by v2
fold it conceptually belongs to `agent_runtime`. v1 reality keeps it inside
integration because the receiver shares its outbox writer, payload model
(`HookEvent`), and process-boundary plumbing with the third-party webhook
subsystem.

## Canonical fields

### Use cases

#### UC-R1: Claude session_start with additional context injection

```gherkin
Given Claude Code is configured with a SessionStart hook pointing at telec-hook
And the project has memory snippets and a configured human-in-the-loop person
When Claude starts a new session and invokes telec-hook with --agent claude --cwd /path/to/project SessionStart
Then the ClaudeAdapter parses JSON payload from stdin
And the receiver maps "SessionStart" to AgentHookEvents.AGENT_SESSION_START
And the receiver resolves the TeleClaude session id (minting one if missing — AGENT_SESSION_START is in mint_events)
And the receiver fetches memory_context + person_header for the project
And prints adapter-formatted additional context to stdout (plain text for Claude)
And persists native_session_id + native_log_file via NATIVE_METADATA_UPDATE outbox row
And enqueues the AGENT_SESSION_START event into the per-session hook outbox
And exits 0
```

#### UC-R2: Stop hook blocked with checkpoint instruction

```gherkin
Given a Claude session has uncommitted turn-local changes
Or the session's current HEAD differs from the turn-start anchor SHA on main
And the persistent checkpoint clear flag is not set
And the per-turn recheck flag has not already fired
When Claude invokes telec-hook ... Stop after the agent attempts to stop
Then the receiver maps "Stop" to AgentHookEvents.AGENT_STOP
And calls _maybe_checkpoint_output which loads the session row and gathers evidence
And get_checkpoint_content returns a non-empty checkpoint reason string
And when HEAD advanced on main, the checkpoint reason includes the post-commit review-gate surfacing action even if no dirty files remain
And enqueue_checkpoint_seen writes a CHECKPOINT_SEEN row to the outbox
And ClaudeAdapter.format_checkpoint_response serializes {"decision":"block","reason":<reason>} to stdout
And the process exits 0 BEFORE enqueueing the original AGENT_STOP event
And Claude reads the JSON from stdout and re-prompts itself with the checkpoint reason
```

#### UC-R3: Codex subagent event dropped pre-resolution

```gherkin
Given Codex emits a hook event from a subagent transcript path
When telec-hook --agent codex receives the event
And the receiver detects is_codex_subagent_transcript(native_log_file) is True
Then the event is dropped BEFORE session resolution runs
And no session-map entry is written that would bind the subagent native id to the parent session
And the receiver exits 0 with no outbox row
And a "subagent_drop" debug log is recorded
```

#### UC-R4: System-injected user_prompt_submit dropped

```gherkin
Given Claude posts a user_prompt_submit event whose prompt body starts with "[TeleClaude Checkpoint]" or other TeleClaude-owned envelope prefixes
When the receiver processes the event
Then _is_system_injected_user_prompt returns True
And the event is dropped (no outbox row written)
And the per-turn recheck flag is NOT reset
```

#### UC-R5: Unhandled hook event silently dropped

```gherkin
Given an agent emits a hook event whose canonical type is not in AgentHookEvents.RECEIVER_HANDLED
When the receiver processes the event
Then a "Dropped unhandled hook event" debug log is emitted
And the process exits 0 with no outbox row written
```

#### UC-R6: Invalid JSON payload — best-effort error path

```gherkin
Given the agent CLI invokes telec-hook with malformed JSON on stdin
When the receiver attempts to parse via the adapter
Then a JSONDecodeError is caught
And _emit_receiver_error_best_effort is invoked with code=HOOK_INVALID_JSON, no raw_data
And inside that helper:
    - raw_native_session_id is None (no raw_data was passed by _parse_receiver_input)
    - _get_cached_session_id(args.agent, None) returns None
    - _find_session_id_by_native(None) returns None
    - the helper logs "Receiver error with unknown session" at error level
    - NO outbox row is enqueued (the function returns without reaching enqueue_hook_event)
And the receiver exits 1

Given a hypothetical caller that did pass raw_data with a resolvable native session id
When _emit_receiver_error_best_effort runs
Then session resolution succeeds and an "error" outbox row IS enqueued
But _parse_receiver_input does NOT pass raw_data on JSON / non-object failures, so this branch is not reached on the JSON parse path
```

#### UC-R7: Receiver re-execs under project venv

```gherkin
Given telec-hook is invoked by an agent CLI from an arbitrary working directory where PATH resolves python3 to system Python
When the receiver __main__ bootstrap resolves the repo root via resolve_state_root
And finds <repo>/.venv/bin/python3
Then os.execv replaces the current process with the project venv interpreter
And the receiver continues with the same argv under the venv interpreter
And all project dependencies are importable
```

### Implementation pointers (v1)

- `teleclaude/hooks/receiver/__init__.py` — `main()` (L807, top-level
  orchestration); `_resolve_receiver_session_id` (L568),
  `_maybe_checkpoint_output` (L234),
  `_maybe_emit_additional_context` (L755),
  `_maybe_emit_checkpoint_response` (L777),
  `_handle_user_prompt_submit` (L723),
  `_persist_native_metadata` (L660),
  `enqueue_hook_event` (L420),
  `_parse_receiver_input` (L526),
  `_emit_receiver_error_best_effort` (L483).
- `teleclaude/hooks/receiver/__main__.py` — script bootstrap, venv re-exec
  (whole file ~43 lines).
- `teleclaude/hooks/receiver/_repo_root.py` — repo-root helper for the
  worktree-safe bootstrap (~19 lines).
- `teleclaude/hooks/receiver/_session.py` —
  `_resolve_hook_session_id` (L406),
  `_load_session_map` (L122),
  `_write_session_map_atomic` (L138),
  `_resolve_or_refresh_session_id` (L251),
  `_get_cached_session_id` (L148),
  `_find_session_id_by_native` (L303),
  `_get_memory_context` (L105).
- `teleclaude/hooks/adapters/base.py` — `HookAdapter` protocol (L66),
  `read_stdin_payload` (L14), `parse_stdin_hook_input` (L28),
  `normalize_common_payload` (L40).
- `teleclaude/hooks/adapters/claude.py` — `ClaudeAdapter` (L13):
  `mint_events = {AGENT_SESSION_START}` (L17),
  `supports_hook_checkpoint = True` (L18).
- `teleclaude/hooks/adapters/codex.py` — `CodexAdapter` (L13):
  `mint_events = {AGENT_SESSION_START, AGENT_STOP}` (L17),
  `supports_hook_checkpoint = True` (L23).
- `teleclaude/hooks/adapters/gemini.py` — `GeminiAdapter` (L13):
  `mint_events = {AGENT_SESSION_START}` (L17),
  `supports_hook_checkpoint = True` (L18).

### Cross-context references

- **Primary home is agent_runtime in v2** per `docs/project/spec/domain/context-map.md`
  ("Agent CLI hooks reach agent_runtime directly via `telec-hook` IPC"). In v1
  the code lives under `teleclaude/hooks/` and is inventoried here per PRD
  scope. The v2 fold moves this whole feature to `agent_runtime`.
- Consumes session-map state from the agent_runtime domain (sessions table,
  native_session_id mapping).
- Emits CHECKPOINT_SEEN, NATIVE_METADATA_UPDATE, NATIVE_SESSION_REFRESH,
  AGENT_SESSION_START, USER_PROMPT_SUBMIT, TOOL_USE, AGENT_STOP, AGENT_ERROR
  rows into the hook outbox (see `hook-event-outbox`).

## Known caveats

- Receiver only emits events listed in `AgentHookEvents.RECEIVER_HANDLED`;
  intermediate hook traffic outside that set is intentionally dropped at the
  process boundary to prevent noisy events reaching daemon handlers.
- Adapter `mint_events` sets are:
  - `ClaudeAdapter.mint_events = {AGENT_SESSION_START}`
  - `GeminiAdapter.mint_events = {AGENT_SESSION_START}`
  - `CodexAdapter.mint_events = {AGENT_SESSION_START, AGENT_STOP}` — Codex
    mints on both session start AND stop because its hook surface emits
    `AGENT_STOP` even when no prior session_start arrived through the
    daemon (e.g., manual `codex` invocations whose first observable hook
    is the stop). For non-mint events on an unknown native session id,
    the receiver drops the event rather than minting.
- `_is_system_injected_user_prompt` filters out TeleClaude-injected prompt
  envelopes (`[TeleClaude Checkpoint]`, `[TeleClaude Notification]`,
  `[TeleClaude Input Request]`, `[TeleClaude Linked output...]`), Codex
  internal `<hook_prompt>` markers, and Claude hook-feedback prefixes
  ("Stop hook feedback:", "PreToolUse hook feedback:") plus internal
  `<task-notification>` / `<system-reminder>` envelopes. Without this filter,
  agents would treat their own injected prompts as new user input and loop.
- All three v1 adapters set `supports_hook_checkpoint = True`. The block
  payload format differs per adapter:
  - `ClaudeAdapter.format_checkpoint_response` →
    `{"decision": "block", "reason": <reason>}`
  - `CodexAdapter.format_checkpoint_response` →
    `{"decision": "block", "reason": <reason>}`
  - `GeminiAdapter.format_checkpoint_response` →
    `{"decision": "deny", "reason": <reason>}`
    When the adapter returns `None` from `format_checkpoint_response`, the
    receiver lets the stop event continue to outbox enqueue, but in v1 none
    of the three adapters return `None`.
- Native metadata persistence (`_persist_native_metadata`) always runs when
  `raw_native_session_id` or `raw_native_log_file` is present. If the new
  native_session_id differs from the row's stored value, a
  `NATIVE_SESSION_REFRESH` outbox row is emitted in addition to the standard
  `NATIVE_METADATA_UPDATE`.
- Hook stdin must be a JSON object (not array, not primitive); the adapter
  raises `ValueError("Hook stdin payload must be a JSON object")` otherwise,
  which `_parse_receiver_input` reports through the same best-effort
  unknown-session path as malformed JSON: a `HOOK_PAYLOAD_NOT_OBJECT` error
  is logged, no error outbox row is enqueued, and the receiver exits 1.
- The receiver swallows DB errors during native-metadata persistence with a
  warning log; the hook event itself is still enqueued.
