# DOR Report: conversation-projection-unification

## Assessment: PASS — Score 9/10

Gate verdict issued by a separate gate worker session. All eight DOR gates satisfied.

## Gate Analysis

### 1. Intent & Success

**Status: PASS**

- Problem statement is explicit: four separate output projection paths with confirmed, codebase-evidenced divergent visibility semantics (the divergence matrix in requirements is grounded in real function signatures and line numbers).
- Required outcome is concrete: one canonical core projection route that all producers/consumers share.
- 10 success criteria in `requirements.md` are testable by inspection or automated test.
- Visibility divergence is not an inference — it is documented against actual code locations (`convert_entry()` at `transcript_converter.py:159`, `extract_messages_from_chain()` at `transcript.py:2224`, etc.).

### 2. Scope & Size

**Status: PASS**

- 6 phases, 15 tasks. Each phase is independently deployable; Phase 1 can land alone, Phase 2 tasks land individually.
- Cross-cutting scope is explicitly called out and bounded: adapters are out of scope, core producers and web API endpoints are in scope.
- This is medium-to-large but phased. No single task exceeds a single session's context budget.
- The builder must commit per phase — the plan makes this explicit.

### 3. Verification

**Status: PASS**

- Phase 3 defines fixture-based regression tests for all three existing output paths.
- The confirmed leak (`convert_entry()` emitting all blocks unfiltered) has a direct regression test: internal tools must not surface in web chat after cutover.
- Web parity test: same transcript → matching visible content for history API and web live SSE.
- Demo plan defines manual verification steps with concrete CLI commands.

### 4. Approach Known

**Status: PASS**

- Every key function reference in the implementation plan was verified against the live codebase:
  - `normalize_transcript_entry_message` at `transcript.py:170` ✓
  - `iter_assistant_blocks` at `transcript.py:207` ✓
  - `render_clean_agent_output` at `transcript.py:491` ✓
  - `render_agent_output` at `transcript.py:1069` ✓
  - `_parse_timestamp` at `transcript.py:670` ✓
  - `_should_skip_entry` at `transcript.py:235` ✓
  - `StructuredMessage` at `transcript.py:2024` ✓
  - `extract_messages_from_chain` at `transcript.py:2224` ✓
  - `trigger_incremental_output` at `agent_coordinator.py:1307` ✓
  - `poll_and_send_output` at `polling_coordinator.py:800` ✓
  - `get_session_messages` at `api_server.py:1182` ✓
  - `_stream_sse` at `streaming.py:146` ✓
  - `convert_entry` in `transcript_converter.py` ✓
- Pattern is consolidation, not invention: projection layer → serializers → transport.
- Existing shared utilities (`StructuredMessage`, `normalize_transcript_entry_message`, `iter_assistant_blocks`) provide the foundation.

### 5. Research Complete

**Status: PASS (auto-satisfied)**

- No new third-party dependencies introduced.
- All existing code paths mapped with verified line numbers.
- Visibility divergence confirmed through codebase inspection.

### 6. Dependencies & Preconditions

**Status: PASS**

- No blocking dependencies on other todos.
- `adapter-boundary-cleanup` and `reflection-routing-ownership` are explicitly out of scope.
- `web-frontend-test-bugs` references this todo as the architectural owner but does not block it.
- No new configuration, env vars, or external systems required.

### 7. Integration Safety

**Status: PASS**

- Phased cutover: each phase can land incrementally without destabilizing main.
- Adapter-facing contracts (`send_output_update()`, `send_threaded_output()`) are explicitly preserved.
- The refactor happens beneath adapter-facing delivery methods, not inside them.
- Rollback: revert the `output_projection/` package and restore direct calls. No data migration involved.

### 8. Tooling Impact

**Status: N/A (auto-satisfied)**

- No scaffolding or tooling changes in this todo.

## Plan-to-Requirement Fidelity

No contradictions found. Every requirement traces to a plan task:

| Requirement | Plan task |
|-------------|-----------|
| Canonical projection route in core | Task 1.1 |
| `conversation` projection for transcripts | Task 1.1 |
| `terminal_live` projection for poller output | Task 1.1 |
| Shared visibility policy | Task 1.1 |
| Poller cutover (no adapter changes) | Task 2.1 |
| Threaded producer cutover (no adapter changes) | Task 2.2 |
| Web history cutover | Task 2.3 |
| Web live SSE cutover | Task 2.4 |
| Explicit user-visible tool allowlist | Task 2.5 |
| Mirror/search handoff | Task 2.6 |
| Preserve `send_output_update()` contract | Task 2.1 |
| Preserve `send_threaded_output()` contract | Task 2.2 |
| Web parity tests | Task 3.1 |
| Threaded-mode regression tests | Task 3.2 |
| Adapter push regression tests | Task 3.3 |
| Bug bucket reference update | Task 4.1 |
| Architecture doc updates | Task 4.2 |

## Assumptions

- `StructuredMessage` is extensible without breaking existing consumers of `to_dict()` / `MessageDTO`. If it is not, the builder introduces a composition wrapper rather than inheritance — both produce the same output contract.
- AI SDK v5 UIMessage Stream SSE format used by `transcript_converter.py` is structurally stable. The cutover changes the input to the converters (projected blocks instead of raw entries), not the output format.
- Mirror/search adoption (Task 2.6) is a handoff point definition only. Full cutover belongs to `history-search-upgrade`.

## Blockers

None. All gates satisfied. No decisions required from the human.

## Gate Score

**9/10**

Deduction: medium-to-large todo with multiple file touch points and a new package introduction carries inherent execution risk even with a clean plan. The phased approach mitigates this but does not eliminate it. The `StructuredMessage` extension assumption is the only unresolved uncertainty (minor, with a clear fallback path).

**Verdict: READY — proceed to build phase.**
