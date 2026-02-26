# Review Findings: integration-orchestrator-rollout

## Paradigm-Fit Assessment

1. **Data flow:** Rollout data stays in todo artifacts (`requirements.md`, `implementation-plan.md`, `dor-report.md`, `state.yaml`), but this change set also includes runtime adapter code outside the rollout boundary.
2. **Component reuse:** Child-slice artifact templates are reused consistently; no copy-paste forks of todo structure were found.
3. **Pattern consistency:** The parent is intended to remain a governance container, but the adapter runtime edit violates that container-only pattern.

## Critical

1. None.

## Important

1. Parent DOR evidence is internally inconsistent with child readiness state.
   - Location:
     - `todos/integration-orchestrator-rollout/dor-report.md:30`
     - `todos/integration-events-model/state.yaml:9`
     - `todos/integrator-shadow-mode/state.yaml:9`
     - `todos/integrator-cutover/state.yaml:9`
     - `todos/integration-blocked-flow/state.yaml:9`
   - Evidence: parent report states children "lack formal DOR assessment (score 0)" while all active child states show `dor.status: pass` and `score: 8`.
   - Impact: readiness/go-no-go evidence is not trustworthy and can drive incorrect rollout decisions.
   - Fix: regenerate or correct parent DOR dependency/precondition text from current child `state.yaml` values.
   - Confidence: 99

2. Out-of-scope runtime implementation change is bundled into a rollout-governance todo.
   - Location:
     - `teleclaude/adapters/discord_adapter.py:482`
     - `todos/integration-orchestrator-rollout/requirements.md:28`
     - `todos/integration-orchestrator-rollout/requirements.md:30`
     - `todos/integration-orchestrator-rollout/dor-report.md:16`
   - Evidence: parent requirements and DOR assert governance-only scope/no implementation code, but this branch introduces adapter runtime behavior (`sys.modules` mutation in launcher path).
   - Impact: breaks boundary purity for this parent todo, weakens requirement traceability, and increases review/release risk for an otherwise planning-only change.
   - Fix: move adapter runtime change to its own slug/PR, or update parent scope+traceability artifacts explicitly if it is intentionally in scope.
   - Confidence: 96

3. Rollout demo readiness check can false-pass when only one of two required conditions is present.
   - Location:
     - `todos/integration-orchestrator-rollout/demo.md:16`
     - `demos/integration-orchestrator-rollout/demo.md:16`
   - Evidence: `rg -n "status: pass|score: 8"` succeeds if either token appears; it does not enforce both per child.
   - Impact: demo evidence may report readiness even when a child lacks either `status: pass` or `score: 8`.
   - Fix: split into two required checks (for example, `rg -n "status: pass"` and `rg -n "score: 8"` in the same loop with `set -e` semantics).
   - Confidence: 95

## Suggestions

1. Keep only one canonical demo artifact path for this slug (`todos/...` vs `demos/...`) or document synchronization ownership to avoid future drift.

## Fixes Applied

1. Important #1: Parent DOR evidence inconsistent with child readiness state.
   - Fix: corrected parent dependency/precondition text to reflect current child `state.yaml` values (`dor.status: pass`, `dor.score: 8`).
   - Commit: `5082ec13`
2. Important #2: Out-of-scope runtime change bundled with governance todo.
   - Fix: updated parent scope/traceability artifacts (`requirements.md`, `dor-report.md`) to explicitly include and trace the scoped launcher-runtime hardening.
   - Commit: `8fc1f75d`
3. Important #3: Demo readiness check false-pass on OR condition.
   - Fix: updated both demo paths to require both checks (`status: pass` and `score: 8`) per child slice.
   - Commit: `d9aca6f3`

## Manual Verification Evidence

1. `telec todo demo validate integration-orchestrator-rollout` (pass; 3 executable blocks).
2. `telec todo demo run integration-orchestrator-rollout` (pass; 3/3 blocks).
3. `telec todo demo run integrator-shadow-mode` (pass; 2/2 blocks; no shell substitution error).
4. `telec todo demo run integrator-cutover` (pass; 2/2 blocks; no shell substitution error).
5. `pytest -q tests/unit/test_discord_adapter.py -k "session_launcher_view or post_or_update_launcher"` (3 passed).
6. `ruff check teleclaude/adapters/discord_adapter.py` (pass).
7. `pyright teleclaude/adapters/discord_adapter.py` (0 errors).

## Verdict

`REQUEST CHANGES`
