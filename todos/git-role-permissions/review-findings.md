# Review Findings: git-role-permissions (Round 2)

**Ad-hoc review (via from-main)**

## Round 1 Finding Verification

All 4 Important findings from round 1 have been addressed:

1. **Orchestrator privilege escalation** — Fixed. `ROLE_ORCHESTRATOR` restored, mapped correctly in `command_service.py`. Git wrapper treats it as worker (fail-closed). Tests confirm.
2. **Push-on-main tests** — Fixed. `TestPushFromMainPermissions` covers all four roles. Tests pass.
3. **Daemon validation** — Fixed. `.strip().lower()` + allowlist + `logger.warning` for unknowns.
4. **Hardcoded strings** — Fixed. Both `worktrees.py` and `dependency_upgrade.py` use `ROLE_SYSTEM` constant.

Suggestion-level findings from round 1 also addressed:

- Finding #5: Invalid role tests added (parametrized).
- Finding #6: Policy doc updated with full permission matrix.
- Finding #8: Terminology updated in commits.md and version-control-safety.md.

## Critical

_(none)_

## Important

_(none — see Resolved During Review)_

## Suggestions

### 1. Variable shadowing in daemon_session.py

**Location:** `teleclaude/daemon_session.py:295,303`

**Finding:** `role` is first assigned from `resolve_session_principal()` at line 295, consumed at
lines 296 and 299, then reassigned to the system_role value at line 303. The shadowing is harmless
(the original value is no longer needed) but reduces readability. Consider naming the second
variable `system_role` or `git_role`.

### 2. auth.py comment stale

**Location:** `teleclaude/api/auth.py:183`

**Finding:** Comment says `system_role: str | None  # e.g. "worker" or None (orchestrator/admin)`.
The parenthetical "(orchestrator/admin)" is misleading — orchestrator IS a valid system_role now.

## Resolved During Review

### ROLE_ORCHESTRATOR missing from auth.py and surface_types.py

**Location:** `teleclaude/api/auth.py:170`, `teleclaude/cli/telec/surface_types.py:113-114`

**Original finding:** The fix for round 1 Finding #1 restored `ROLE_ORCHESTRATOR` in
`constants.py`, `command_service.py`, and `daemon_session.py` but missed two consumption sites:

- `auth.py:_derive_session_system_role` validated against `{worker, system, integrator}` — missing
  orchestrator. Orchestrator sessions would get `CallerIdentity.system_role = None`, breaking API
  auth for orchestrator-gated commands.
- `surface_types.py:_SYS_ORCH` = `{system, integrator}` and `_SYS_ALL` = `{worker, system,
integrator}` — missing orchestrator. CLI commands gated to these sets would reject orchestrator
  sessions.

**Fix applied:**

- Added `ROLE_ORCHESTRATOR` to `auth.py:_derive_session_system_role` allowlist.
- Added `ROLE_ORCHESTRATOR` to `_SYS_ORCH` and `_SYS_ALL` in `surface_types.py`.
- All 32 auth tests + 69 other tests pass.

### Git wrapper header comment stale

**Location:** `teleclaude/install/wrappers/git:8`

**Original finding:** Header listed "Roles: worker (default), integrator, system" — missing
orchestrator. The wrapper doesn't grant orchestrator special permissions, but documenting it as a
recognized role value improves clarity.

**Fix applied:** Updated to "Roles: worker (default), orchestrator, integrator, system."

## Lane Summaries (Round 2)

### Code (next-code-reviewer)

Delegated. Independently confirmed all round 1 fixes are correct. Surfaced the same
auth.py/surface_types.py allowlist drift (auto-remediated) and wrapper header comment (auto-remediated).

### Tests (next-test-analyzer)

Delegated. New tests are well-structured, behavioral, and follow existing patterns. 25 wrapper
tests + 32 auth tests + 12 daemon tests all pass (69 total across changed test files).

### Errors (next-silent-failure-hunter)

Delegated. Daemon validation fix is correct fail-closed behavior. No remaining silent failure paths
in the changed code.

### Principles

No violations. The four-role model maintains clear separation: orchestrator has auth-level
privileges but worker-level git access. `ROLE_SYSTEM` constant eliminates string literal drift.
Validation at daemon injection point closes the normalization gap.

### Paradigm-fit

Fixes follow established patterns. Constants in `constants.py`, validation at bootstrap boundary,
tests per permission domain.

### Security

No new attack surface. The allowlist drift fix (auth.py/surface_types.py) restores correct
permission boundaries. Wrapper fail-closed default remains intact.

### Comments

Wrapper header and policy docs now accurately document all four roles. auth.py comment is stale
(Suggestion #2) but cosmetic.

### Logging

The `logger.warning` for unrecognized roles provides adequate observability.

### Types

No type design changes.

### Simplify

The role model is now clean: four constants, consistent allowlists, single source of truth. No
further simplification needed.

## Why No Issues

- **Paradigm-fit verified:** All fixes follow existing patterns (constants module, bootstrap env
  injection, test class-per-permission-domain).
- **Requirements met:** The core requirement — derive git wrapper permissions from existing
  system_role — is satisfied with proper separation of auth role from git permission role.
- **Copy-paste checked:** Role allowlists now consistent across all three consumption sites
  (daemon_session.py, auth.py, surface_types.py).
- **Security reviewed:** Fail-closed wrapper default intact. No privilege escalation paths.
  Validation and normalization consistent across code paths.

## Verdict

**APPROVE** — 0 Critical, 0 Important findings. 2 Suggestions (cosmetic). 2 findings resolved
during review via auto-remediation.
