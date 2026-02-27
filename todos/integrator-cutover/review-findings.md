# Review Findings: integrator-cutover

## Requirements Tracing

| Requirement                                          | Implemented                                                                                          | Tested             |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------ |
| FR1.1: Only integrator may merge/push canonical main | Shell wrappers (git, gh, pre-push) + Python runtime (`require_integrator_owner`)                     | Unit + integration |
| FR1.2: Non-integrator fails fast with diagnostics    | `INTEGRATOR_MAIN_AUTH_BLOCKED` error in all three shell layers + `IntegrationRuntimeError` in Python | Unit + integration |
| FR2.1: Cutover enabled only after parity evidence    | Config validator + shell parity check + `resolve_cutover_mode()`                                     | Unit (Python)      |
| FR2.2: Explicit rollback on incomplete parity        | `rollback_on_incomplete_parity` flag in controls + shell rollback message                            | Unit               |
| FR3.1: Workers may still push feature branches       | Shell guard scoped to canonical context only                                                         | Integration        |
| FR3.2: Existing branch-based workflows intact        | Cutover checks gated behind `TELECLAUDE_INTEGRATOR_CUTOVER_ENABLED`                                  | Integration        |

## Paradigm-Fit Assessment

1. **Data flow**: Uses established patterns — Pydantic for config schema, frozen dataclasses for domain types, shell wrappers for git/gh guardrails. No inline hacks or bypasses.
2. **Component reuse**: `IntegratorShadowRuntime` extended with optional parameters (backward compatible). `authorization.py` is a new module following the existing `integration/` package structure.
3. **Pattern consistency**: Shell guardrail blocks follow the established `GUARDRAIL_MARKER` + `log_block` + error-message pattern from the pre-existing wrapper code. Python authorization follows the existing `RuntimeError` subclass pattern.

## Critical

(none)

## Important

(none)

## Suggestions

### S1: Missing integration test for `INTEGRATOR_CUTOVER_NOT_READY` shell path

**Files:** `tests/integration/test_integrator_cutover.py`

The three integration tests cover blocked-non-integrator, allowed-integrator, and allowed-feature-branch. There is no test for the case where `TELECLAUDE_INTEGRATOR_CUTOVER_ENABLED=1` but `TELECLAUDE_INTEGRATOR_PARITY_EVIDENCE` is not `"accepted"`. The `INTEGRATOR_CUTOVER_NOT_READY` code path in all three shell scripts is uncovered at the integration level. The Python runtime covers the parity rollback path via `test_shadow_runtime_rolls_back_to_shadow_mode_when_parity_is_incomplete`, so the logic is tested — just not at the shell layer. Adding a fourth integration test would close this gap.

### S2: FR1.1 integration test could assert absence of error markers

**File:** `tests/integration/test_integrator_cutover.py:108-136`

`test_integrator_canonical_main_push_still_succeeds` asserts `returncode == 0` and correct stdout, but does not assert `INTEGRATOR_MAIN_AUTH_BLOCKED not in stderr`. Adding negative assertions would make the test explicitly prove the guard was traversed and passed rather than skipped.

### S3: Config success-path test uses direct construction, not YAML loader round-trip

**File:** `tests/unit/test_config_schema.py:393-400`

`test_integrator_cutover_can_be_enabled_when_parity_accepted` constructs `IntegratorCutoverConfig` directly while `test_integrator_cutover_requires_parity_before_enable` uses `load_project_config`. The pair is asymmetric. Running the success case through the loader too would close a potential serialization gap.

### S4: `gh` wrapper cutover guardrail has no integration test coverage

**File:** `teleclaude/install/wrappers/gh`

The integration tests exercise only the `git` wrapper. The `gh pr merge` cutover guard (lines 185-209) is untested at integration level. The logic mirrors the `git` wrapper exactly, so the risk is low, but coverage would prevent silent regression.

## Why No Important+ Issues

1. **Paradigm fit verified**: New code follows established wrapper patterns (shell) and module structure (Python). No copy-paste duplication — the shell cutover block is identical across three files by design (standalone scripts must be self-contained). The Python `authorization.py` module is properly separated from `runtime.py`.
2. **Requirements met**: All six functional requirements traced to implementation and test coverage. The shell parity check (FR2.1) is the only gap at the integration-test level, but it is covered at the unit level and the shell logic is structurally identical to the role check which IS integration-tested.
3. **Copy-paste duplication checked**: The `_is_truthy`/`is_truthy` function and the cutover guard block are repeated across `pre-push`, `wrappers/git`, and `wrappers/gh`. This is intentional — each is a standalone shell script. `IntegratorCutoverControls` (dataclass) vs `IntegratorCutoverConfig` (Pydantic model) are distinct types in different layers (domain vs config) — not duplication.
4. **Defense-in-depth design noted**: The Python layer uses session-ID-prefix convention (`_default_is_integrator`), the shell layer uses `TELECLAUDE_SYSTEM_ROLE` env var. These are independent enforcement layers at different levels (runtime vs shell guardrail) with the Python predicate being injectable. The asymmetry is intentional.

## Verdict: APPROVE
