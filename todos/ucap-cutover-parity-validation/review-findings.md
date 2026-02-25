# Review Findings - ucap-cutover-parity-validation

## Review Scope

Branch `ucap-cutover-parity-validation` vs `main` (merge-base).

Changed files: documentation/planning artifacts only — no production code was modified.

- `demos/ucap-cutover-parity-validation/demo.md` (new)
- `todos/roadmap.yaml` (adds ucap-slo-hardening dependency)
- `todos/ucap-cutover-parity-validation/implementation-plan.md` (tasks checked with evidence)
- `todos/ucap-cutover-parity-validation/quality-checklist.md` (new, build gates checked)
- `todos/ucap-cutover-parity-validation/state.yaml` (state updates)
- `todos/ucap-slo-hardening/*` (follow-up todo scaffolding)

## Paradigm-Fit Assessment

- **Data flow**: No production code changes. Validation performed through existing test infrastructure and code audit. No paradigm violations.
- **Component reuse**: N/A — no new components introduced.
- **Pattern consistency**: Todo structure, demo format, and quality checklist follow established project conventions.

## Requirements Traceability

### R1. Controlled shadow/cutover — PASS

Shadow mode is structural: `AdapterClient._ui_adapters()` (adapter_client.py:84-87) filters to `isinstance(adapter, UiAdapter)` only. RedisTransport extends `BaseAdapter` (not `UiAdapter`), so it is excluded from all output delivery at the type level. Three pilot scenarios are mapped to integration tests covering origin routing, multi-UI parity, and user input reflection. Scorecard assertions enforce no missing outputs and exactly one call per adapter per output event.

### R2. Parity criteria and rollback triggers — PASS

Lightweight pilot criteria (no missing outputs, at most one duplicate) are enforced via test assertions. Rollback trigger/exit documented. `test_observer_failure_does_not_affect_origin` demonstrates observer fault isolation with origin delivery preserved. Clean-pass evidence follows in subsequent test runs.

### R3. Legacy bypass retirement — PASS

Grep audit of `teleclaude/` confirmed: all `send_message`, `send_output_update`, and `send_threaded_output` calls route through `AdapterClient`. The two `adapter.send_message()` calls inside `adapter_client.py` (lines 606 and 860) are within the adapter_client's own internal routing methods (`broadcast_user_input` via `_fanout_excluding`, and event broadcast with `isinstance(adapter, UiAdapter)` guard) — they ARE the unified path. No direct adapter calls bypass the routing layer for core output progression.

### R4. Cross-client validation — PASS

Integration tests cover Telegram (origin routing), Discord/Slack stand-in (UI observer), Redis (excluded via `has_ui=False`). Web/TUI coverage via `test_agent_activity_broadcast.py` on main. All 8 multi-adapter broadcasting tests pass (verified during review).

## Acceptance Criteria

1. Shadow mode documented via test mapping — **MET**
2. Outputs visible across clients with no missing/excess — **MET**
3. Rollback exercised with return to known-good — **MET**
4. No legacy bypass path exercised — **MET**
5. Demo artifacts with commands, outcomes, residual risks — **MET**

## Critical

None.

## Important

1. **Uncommitted working tree regression in implementation-plan.md** — The working tree has reverted all task checkboxes from `[x]` to `[ ]` and removed all evidence comments. The committed version (in git) is correct and contains the full evidence trail. This uncommitted revert must be discarded before finalize — if committed, it would erase all build evidence. Resolution: `git checkout -- todos/ucap-cutover-parity-validation/implementation-plan.md` to restore the committed version.

2. **state.yaml committed as `build: started` instead of `build: complete`** — The committed state is inconsistent with the quality checklist which shows build complete. The working tree has the correct `build: complete` value but it is uncommitted. Resolution: commit the state.yaml update.

## Suggestions

1. The demo's third validation block (`instrukt-ai-logs teleclaude --since 10m --grep ...`) is environment-dependent and may produce no output in CI or cold environments. Consider adding a note about expected output or making it optional.

2. The `MockSlack` adapter in tests is used as a stand-in for Discord observer behavior. The mapping is documented only in implementation-plan comments. Acceptable for a pilot but worth a code comment in the test file if the pattern persists.

## Manual Verification Evidence

- Verified `_ui_adapters()` filter at adapter_client.py:84-87 — structurally excludes non-UiAdapter types.
- Verified bypass audit via grep: all output calls in `teleclaude/` route through `AdapterClient` methods.
- Ran `pytest -q tests/integration/test_multi_adapter_broadcasting.py` — 8 passed.
- Integration test suite (`make test-e2e`) — 96 passed.

## Verdict: APPROVE

The committed work correctly validates all requirements. The codebase evidence (existing tests, routing architecture, grep audit) substantiates the builder's claims. The two Important findings are clerical (uncommitted working tree state) and do not affect the substantive delivery. They must be resolved before finalize.
