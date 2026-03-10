# Review Findings: session-role-metadata

**Review round:** 1
**Reviewer:** Claude (automated)
**Scope:** All commits since merge-base (`18cb150b..HEAD`)

## Verdict: APPROVE

All implementation-plan tasks completed (`[x]`). No deferrals. 151 targeted unit tests pass.
All requirements traceable to implementation. No gold-plating or scope gaps detected.

---

## Critical

None.

---

## Important

None unresolved. One finding was auto-remediated during review.

---

## Resolved During Review

### 1. Missing planned test — `test_list_sessions_job_filter_respects_role_visibility`

**Location:** `tests/unit/test_session_list_job_filter.py`
**Severity:** Important (before remediation)
**Description:** Implementation plan Task 5 specifies `test_list_sessions_job_filter_respects_role_visibility` to verify that web/member visibility rules still apply before job filtering. This test was absent from the delivered test file.
**Remediation:** Added the test. It verifies that role-based visibility filtering (e.g., public vs private) narrows results before the job filter is applied. Test passes.

### 2. Guard non-zero exit falls through without logging

**Location:** `teleclaude/core/integration_bridge.py:293`
**Severity:** Important (before remediation)
**Description:** When `telec sessions list --all --job integrator` returns a non-zero exit code (daemon 500, auth rejection, etc.), the guard fell through to spawn without logging the failure or stderr. The behavior (fail-open, proceed to spawn) is correct by design, but the observability gap meant no log evidence when the guard was bypassed by a transient error.
**Remediation:** Added explicit `logger.warning` for the non-zero return code path, including exit code and stderr. The fail-open behavior is preserved.

---

## Suggestions

### 1. `COMMAND_ROLE_MAP` uses string literals instead of constants

**Location:** `teleclaude/api_server.py:142-155`
**Description:** The map uses `"worker"`, `"orchestrator"`, `"integrator"` string literals rather than `ROLE_WORKER`, `ROLE_ORCHESTRATOR`, `ROLE_INTEGRATOR` from `teleclaude/constants.py`. Using constants would prevent drift if the canonical strings ever change.

### 2. `get_excluded_tools()` `role` parameter is suppressed and unused

**Location:** `teleclaude/core/tool_access.py:33`
**Description:** The `role` parameter is suppressed with `# noqa: ARG001` and not passed to `is_command_allowed()`. The function always evaluates exclusions as if `system_role=None` (orchestrator). All current callers pass `None`, and this function has no production callers (only test consumers), so there is no runtime impact. If a future caller passes a non-None role, it would silently receive orchestrator-level exclusions.

### 3. `filter_tool_names` fails closed for non-`telec`-prefixed tool names

**Location:** `teleclaude/core/tool_access.py:56-58`
**Description:** Tool names not starting with `"telec "` are passed as-is to `is_command_allowed()`, which returns `False` for unrecognized paths. This means non-telec tools in the list are silently excluded. No production callers exist, so impact is zero. The old code also didn't handle this case (it checked against exclusion sets that only contained `telec ` prefixed names).

### 4. Job filter and metadata injection lack endpoint-level (TestClient) tests

**Description:** `test_session_list_job_filter.py` replicates the filter predicate inline rather than exercising the `GET /sessions?job=` endpoint through a `TestClient`. Similarly, `test_run_session_metadata.py` tests `COMMAND_ROLE_MAP` dict contents but not the `run_session()` wiring that injects `session_metadata` into the session. This means API-layer regressions (missing query param wiring, injection code removed) would not be caught. Unit-level behavior is covered; the gap is at the functional/integration test layer. Follow-up: add `TestClient`-based tests for both paths.

### 5. No edge-case test for `session_metadata=None` (pre-migration sessions)

**Description:** Requirements note the risk of legacy sessions without `job` metadata. The job filter guard (`isinstance(s.session_metadata, dict)`) and `_derive_session_system_role()` fallback are correct by inspection, but there is no test for `session_metadata=None` or non-dict values. The `_make_session(job=None)` helper produces `{}` (empty dict), which is close but not the same as `None`. Follow-up: add explicit `None`-metadata test cases.

### 6. Dead code in mirror test `elif` branch

**Location:** `tests/unit/test_command_auth.py:388-389`
**Description:** The condition `ROLE_INTEGRATOR in (cmd.auth.system - {ROLE_INTEGRATOR})` can never be true (the role is removed from the set before checking membership). The branch is unreachable. The assertion logic is still correct — whitelisted paths are checked, and non-whitelisted paths are checked — but the dead `elif` is confusing.

---

## Lane Summary

| Lane       | Result   | Notes                                                                  |
|------------|----------|------------------------------------------------------------------------|
| scope      | Pass     | All requirements traced; no gold-plating                               |
| code       | Pass     | No bugs found; contract fidelity verified                              |
| paradigm   | Pass     | Follows established CommandAuth, CLI_SURFACE, daemon auth patterns     |
| principles | Pass     | No unjustified fallbacks; integration bridge fail-open is by design    |
| security   | Pass     | No secrets, no injection, server-side metadata derivation enforced     |
| tests      | Pass     | 152 tests pass (151 original + 1 added during review); coverage adequate |
| errors     | Pass     | Exception handling appropriate; guard fail-open is documented design   |
| types      | Pass     | No new types introduced beyond `COMMAND_ROLE_MAP` dict                 |
| comments   | Pass     | Comments in `tool_access.py` and `auth.py` accurate                    |
| demo       | Pass     | 5 executable blocks; commands and imports match actual code             |
| docs       | Pass     | `--job` flag documented in CLI_SURFACE and help text                    |

## Why No Critical/Important Issues

1. **Paradigm-fit verified:** The implementation follows the established CommandAuth declaration pattern in `CLI_SURFACE`, uses the same `_SYS_*` / `_HR_*` shorthand conventions, and routes through existing `require_clearance()` and `_is_tool_denied()` paths.
2. **Requirements coverage verified:** Each success criterion in `requirements.md` maps to at least one test. The integrator-allowed/blocked command matrix is encoded in the `test_integrator_cli_auth_mirrors_whitelist` invariant test.
3. **Copy-paste duplication checked:** `COMMAND_ROLE_MAP` is the single source for role derivation; selective `_SYS_INTG` union is applied per-command without duplicating the integrator set definition.
4. **Security reviewed:** `RunSessionRequest` has no `session_metadata` field; metadata is derived server-side from `COMMAND_ROLE_MAP`. Dual-factor auth (system_role + human_role) enforced via `is_command_allowed()`.
5. **Integration bridge fail-open design:** The guard catches `TimeoutExpired`, `FileNotFoundError`, and `JSONDecodeError` and proceeds to spawn. This is the correct design — a permanently blocked integrator queue is worse than a briefly duplicated integrator. The old text-grep guard had the same fail-open behavior.
