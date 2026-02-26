# Review Findings: integration-orchestrator-rollout

Date: 2026-02-26
Verdict: REQUEST CHANGES

## Critical

- None.

## Important

1. Parent rollout scope is violated by runtime adapter code in this slug.
   - Location:
     - `teleclaude/adapters/discord_adapter.py:482`
     - `todos/integration-orchestrator-rollout/requirements.md:28`
     - `todos/integration-orchestrator-rollout/dor-report.md:16`
   - Evidence:
     - The parent requirements mark implementation internals as out of scope.
     - The DOR report states "No implementation code in this slug."
     - The branch still changes production runtime behavior (`sys.modules.setdefault("discord", self._discord)` in launcher view creation).
   - Impact: breaks rollout-container boundary and weakens requirement-to-implementation traceability.
   - Recommended fix: move adapter runtime hardening into its own implementation slug/PR, or explicitly re-scope the parent requirements and DOR evidence to include this runtime change.
   - Confidence: 97

2. Parent DOR evidence contradicts current child readiness facts.
   - Location:
     - `todos/integration-orchestrator-rollout/dor-report.md:30`
     - `todos/integration-events-model/state.yaml:9`
     - `todos/integrator-shadow-mode/state.yaml:9`
     - `todos/integrator-cutover/state.yaml:9`
     - `todos/integration-blocked-flow/state.yaml:9`
   - Evidence:
     - Parent DOR claims children "lack formal DOR assessment (score 0)."
     - All four child state files currently report `dor.status: pass` and `score: 8`.
   - Impact: rollout go/no-go evidence is not reliable.
   - Recommended fix: regenerate the parent DOR dependencies/preconditions section from current child state values.
   - Confidence: 99

## Suggestions

1. Manual verification gap (required for user-facing Discord behavior): this environment cannot validate live Discord UX (persistent launcher registration, forum post/update/pin behavior) against real guild state. Run a manual guild smoke pass before approval.

## Paradigm-Fit Assessment

1. Data flow: parent todo should stay in governance/process artifacts, but this branch mixes in adapter runtime mutation.
2. Component reuse: child-slice artifact structure is reused consistently; no copy-paste component fork detected.
3. Pattern consistency: DOR/requirements claim container-only scope, but the runtime adapter edit deviates from that pattern.

## Manual Verification Evidence

1. `pytest -q tests/unit/test_discord_adapter.py -k "session_launcher_view or post_or_update_launcher"` passed (3 tests).
2. `ruff check teleclaude/adapters/discord_adapter.py` passed.
3. `pyright teleclaude/adapters/discord_adapter.py` passed (0 errors).
4. Live Discord manual verification was not possible from this environment.

## Fixes Applied

1. Important #1 (parent rollout scope violated by runtime adapter code)
   - Fix: removed `sys.modules.setdefault("discord", self._discord)` and its related comment from launcher view creation in `teleclaude/adapters/discord_adapter.py`.
   - Commit: `d9e11d37`
2. Important #2 (parent DOR evidence contradicted child readiness facts)
   - Fix: regenerated Dependencies & Preconditions evidence to reflect current child `dor.status=pass` and `dor.score=8` values.
   - Commit: `5fb4a538`
