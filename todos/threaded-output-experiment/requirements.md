# Requirements: Threaded Agent-Stop Output

## Goal
On each handled `agent_stop` event, send one normal Telegram message that summarizes the latest assistant activity from transcript data (not pane output), instead of relying on output-pane edit semantics for that stop-turn update.

## Config Model
Configuration must be loaded from optional `experiments.yml` (not `experiments.yaml`), merged as an overlay on top of base config.

### File convention
- Config file extension convention in this repo is `.yml` (not `.yaml`).

### Source files
1. Required base config: `config.yml`
2. Optional overlay: `experiments.yml`

### Overlay behavior
- If `experiments.yml` is absent: ignore, no failure, no `experiments` behavior enabled.
- If present: merge into final runtime config as an extra `experiments` leaf.
- `experiments.yml` should not require edits to `config.yml`.
- For this todo rollout, `experiments.yml` must be added with Gemini-only entries.

## Experiment Schema
`experiments` is a list of objects:

```yml
experiments:
  - name: ui_threaded_agent_stop_output
    agents: [gemini]
  - name: ui_threaded_agent_stop_output_include_tools
    agents: [gemini]
```

Rules:
1. `name: str` required.
2. `agents: list[str]` optional.
3. Missing/empty `agents` means all agents.
4. Agent values must match runtime agent keys (`claude`, `gemini`, `codex`).

## Functional Behavior
1. Event handling
- For every handled `agent_stop` event, evaluate experiment match for that session’s active agent.
- If matched, send threaded stop output via `AdapterClient.send_message`.
- If not matched, keep legacy behavior.

2. Transcript source of truth
- Build message content from transcript parsing only.
- Do not use DB summary fields like `last_message_sent` as message content input.

3. Message composition (default)
- Collect assistant activity since the last user boundary:
  - assistant text/output_text blocks as normal text,
  - assistant thinking blocks as italic markdown.
- Exclude tool call/results by default.

4. Optional tools inclusion
- Add formatter/parser flag `include_tools: bool`.
- Drive this by experiment `ui_threaded_agent_stop_output_include_tools`.
- If tools included, existing collapse rendering behavior may be used.

5. Telegram delivery format
- Send one normal message per handled stop event.
- Use markdown-compatible formatting path.
- Do not wrap whole message in triple-backtick code fences.

## Explicit Non-Goals
- No user-message mirroring as bot output.
- No per-message cursor/count persistence for threaded sends.
- No generic feature-flag framework beyond experiment list matching.
- No broad polling architecture rewrite.

## Known Event Boundaries (must be preserved)
These are current intentional non-delivery conditions and should remain explicit in behavior/docs:
1. Unknown session for non-`session_start` events is ignored.
2. Closed sessions ignore incoming hook events.
3. Gemini split path only emits `agent_stop` when `prompt_response` is non-empty.
4. Non-retryable outbox errors (e.g., session not found) are dropped.

## Acceptance Criteria
1. Config/overlay
- `experiments.yml` optional and safely ignored when absent.
- `.yml` convention used for new config file.
- Experiments list parsed and matched by name + agent list.
- Activation for this work is via a committed `experiments.yml` configured for Gemini-only.

2. Delivery semantics
- With `ui_threaded_agent_stop_output` enabled for agent, each handled `agent_stop` produces one threaded message.
- Message content comes from transcript assistant activity since last user boundary.
- Thinking is italic; text is plain.

3. Tools toggle
- Without include-tools experiment: tool call/result content absent.
- With include-tools experiment for matching agent: tool content appears using existing formatter style.

4. Backward compatibility
- Non-matching agents and disabled experiments keep legacy behavior.
- Existing summary/TTS/notification state updates remain intact.
