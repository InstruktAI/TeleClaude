# Review Findings: auto-architecture-diagrams

## Critical

- [R1-F1] Runtime matrix extraction does not produce per-agent feature support from the runtime adapters/config it claims to parse. `scripts/diagrams/extract_runtime_matrix.py:12` targets `teleclaude/adapters/` (UI transports), while runtime-specific normalization lives under `teleclaude/hooks/adapters/`. The matcher in `scripts/diagrams/extract_runtime_matrix.py:159` only links features when adapter filename contains an agent name, which never occurs for `base_adapter.py`, `telegram_adapter.py`, and `ui_adapter.py`; generated output has no agent->feature edges for blocking/transcript behavior. This violates the requirement that runtime matrix reflect per-agent feature support from code.

- [R1-F2] Event-flow handler linkage is not extracted from real handler dispatch and is partially hardcoded. `scripts/diagrams/extract_events.py:111` collects `AgentHookEvents.*` constants referenced in `handle_event`, not the actual handler method names (`handle_session_start`, etc.). Then `scripts/diagrams/extract_events.py:172` uses a hardcoded `handler_map` to wire internal events. This can silently drift and does not satisfy the requirement to derive runtime->event->handler flow from actual code.

- [R1-F3] State and command transitions are hardcoded instead of extracted, so diagrams are not "from code parsing alone" and are maintenance-sensitive. `scripts/diagrams/extract_state_machines.py:21` and `scripts/diagrams/extract_state_machines.py:29` hardcode lifecycle transitions; `scripts/diagrams/extract_commands.py:106` hardcodes orchestration edges. Any workflow change in source logic/docs can desynchronize diagrams without extractor changes.

## Important

- [R1-F4] The new extractor scripts are not covered by the repository type-check gate. `pyrightconfig.json` includes only `teleclaude`, so `scripts/diagrams/*.py` are excluded from enforced checks. Running `uv run mypy scripts/diagrams` currently reports errors in `scripts/diagrams/extract_commands.py:51`. This is a policy gap for new automation code.

- [R1-F5] No automated regression tests were added for six new extraction scripts, despite behavior depending on AST shape and file conventions. Current validation is manual (`make diagrams`) and cannot prevent future silent drift.

## Suggestions

- Add fixture-based unit tests per extractor with small source fixtures and expected Mermaid snapshots.
- Add a targeted CI check that runs `make diagrams` and validates key expected nodes/edges from current source (behavioral assertions, not prose locking).

Verdict: REQUEST CHANGES

## Fixes Applied

- Issue: [R1-F1]
  Fix: Reworked runtime matrix extraction to use runtime hook sources (`teleclaude/hooks/adapters/*.py`, `AgentHookEvents.HOOK_EVENT_MAP`, `AGENT_PROTOCOL`, checkpoint blocking path) and emit per-agent feature edges directly from parsed code.
  Commit: `1bf5a2b9`

- Issue: [R1-F2]
  Fix: Reworked event-flow extraction to derive `event -> handler` links from real `AgentCoordinator.handle_event` dispatch branches and resolved internal event values from `AgentHookEvents` constants, removing hardcoded handler wiring.
  Commit: `c68955d6`

- Issue: [R1-F3]
  Fix: Removed hardcoded lifecycle/command transitions and now parse roadmap/phase transitions plus dispatch/post-completion edges from `teleclaude/core/next_machine/core.py`.
  Commit: `11062dc1`

- Issue: [R1-F4]
  Fix: Extended enforced type-check scope to include `scripts/diagrams` in `pyrightconfig.json` and fixed strict typing issues in extractor scripts so `pyright`/`mypy` pass.
  Commit: `22497835`

- Issue: [R1-F5]
  Fix: Added automated regression coverage for all six extractor scripts with behavior assertions on parsed edges/nodes to catch AST/flow drift.
  Commit: `35a74d25`
