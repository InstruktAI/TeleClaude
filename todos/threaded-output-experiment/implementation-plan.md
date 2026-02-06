# Implementation Plan: Threaded Agent-Stop Output

## Objective
Implement experiment-driven threaded stop-turn output so another agent can execute without interpretation gaps.

## Final Design Decisions
1. Use optional `experiments.yml` overlay (not `config.yml` edits for experiments).
2. Use experiment list objects: `{name, agents}`.
3. Emit threaded message on each handled `agent_stop` for matching agents.
4. Compose message from transcript assistant activity since last user boundary.
5. Add parser/formatter flag to include/exclude tools; tools excluded by default.
6. Initial rollout target is Gemini only.

## Experiments To Implement
1. `ui_threaded_agent_stop_output`
- Enables threaded stop output behavior.

2. `ui_threaded_agent_stop_output_include_tools`
- Enables tool call/result rendering in threaded stop output formatter.
- Independent toggle, evaluated per agent.

## Config Work
### Files
- `teleclaude/config.py`
- new optional root file: `experiments.yml`

### Tasks
1. [x] Add typed experiments model in config:
- Runtime-friendly structure that supports list entries with:
  - `name: str`
  - `agents: list[str] | None`

2. [x] Add optional overlay load:
- Read `experiments.yml` if present.
- Deep-merge into merged raw config as extra leaf.
- If missing, continue normally.

3. [x] Create rollout file for this todo:
- Add `experiments.yml` at repo root with Gemini-only scope:

```yml
experiments:
  - name: ui_threaded_agent_stop_output
    agents: [gemini]
  - name: ui_threaded_agent_stop_output_include_tools
    agents: [gemini]
```

4. [x] Add experiment matcher helper(s):
- `is_experiment_enabled(name: str, agent: str | None) -> bool`
- Match logic:
  - Name exists in experiments list.
  - Agents list empty/missing -> all.
  - Otherwise `agent` must be in list.

## Parser/Formatter Work
### Files
- `teleclaude/utils/transcript.py`

### Tasks
1. [x] Add a dedicated helper for stop-turn rendering:
- Input:
  - transcript path
  - agent name
  - include_tools: bool
- Output:
  - markdown text for one stop-turn message

2. [x] Rendering semantics:
- Include assistant text blocks.
- Include assistant thinking blocks (italic style).
- Exclude tool blocks when `include_tools=False`.
- Include tool blocks when `include_tools=True` (reuse existing formatting/collapse behavior where practical).
- No outer code fence wrapper.

3. [x] Boundary semantics:
- Collect assistant activity since last user boundary.
- If no new assistant activity, return empty/None and skip send.

## Agent-Stop Integration
### File
- `teleclaude/core/agent_coordinator.py`

### Tasks
1. [x] In `handle_stop`, after current transcript/session resolution and before completion:
- Determine active agent.
- Evaluate `ui_threaded_agent_stop_output` for that agent.
- If not enabled: keep existing behavior unchanged.

2. [x] If enabled:
- Evaluate `ui_threaded_agent_stop_output_include_tools`.
- Build stop-turn message from transcript helper with corresponding `include_tools`.
- Send via `self.client.send_message(..., ephemeral=False)` as normal message.

3. [x] Keep existing side effects intact:
- DB feedback/summaries.
- TTS behavior.
- session listener notification forwarding.
- remote initiator forwarding logic.

4. [x] Do not add user-message mirroring.

## Event Handling Notes (for implementer awareness)
These conditions already exist; do not accidentally “fix” them in this todo:
1. Unknown non-start sessions are ignored in hook dispatch.
2. Closed sessions ignore hook events.
3. Gemini split path only creates `agent_stop` when `prompt_response` is present.
4. Some non-retryable outbox errors are dropped.

This todo changes behavior for handled `agent_stop` events, not outbox/session lifecycle policy.

## Test Plan
### Unit tests
1. Config overlay tests
- `experiments.yml` missing -> no crash, no experiments enabled.
- `experiments.yml` present -> experiments parsed correctly.
- Name + agent matching logic works.

2. Transcript formatter tests (`tests/unit/test_transcript.py`)
- thinking/text included.
- tools excluded by default.
- tools included when flag true.
- user boundary respected.

3. Coordinator tests (`tests/unit/test_daemon.py` or focused coordinator tests)
- experiment disabled -> legacy path.
- experiment enabled + agent match -> threaded `send_message` called.
- experiment enabled + agent mismatch -> legacy path.
- include-tools experiment toggles parser include_tools input.

### Manual verification
1. Add `experiments.yml` with:
- threaded output enabled for `gemini`.
- include-tools disabled.
2. Trigger gemini turn completion:
- one normal message per handled stop event.
- thinking italic, text plain, no tools.
3. Enable include-tools experiment for gemini:
- tool formatting appears.
4. Remove/disable experiments:
- legacy behavior returns.

## Rollout
1. Start with `agents: [gemini]` in `experiments.yml` (required for activation in this todo).
2. Observe behavior quality.
3. Expand agent coverage in `experiments.yml` when stable.

## Out Of Scope
- Changing hook emission policy.
- New persistent cursor model for threaded sends.
- Rewriting output poller architecture.
