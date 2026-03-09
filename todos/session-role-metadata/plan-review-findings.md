# Plan Review Findings: session-role-metadata

## Requirement Coverage

The plan covers the main behavior chain from the requirements:

- integrator role constant and whitelist
- auth derivation for `system_role`
- server-side metadata derivation for `sessions run`
- job-based session filtering
- integration bridge spawn-guard replacement

No orphan requirements or obvious gold-plating were found. The issues below block approval because they leave the authorization model and grounding metadata inconsistent with the stated requirements.

## Critical

### 1. `_SYS_ALL` expansion would over-authorize integrator sessions

Task 6 proposes:

- adding `ROLE_INTEGRATOR`
- widening `_SYS_ALL` to include integrator
- relying on that expansion so all existing `_SYS_ALL` commands "implicitly include integrator"

That contradicts the requirement to keep CLI help/auth metadata aligned with the runtime permission model. In the current CLI auth implementation, `is_command_allowed()` trusts `CommandAuth` directly. If `_SYS_ALL` is widened, integrator sessions would become CLI-authorized for many commands that are not in the planned `INTEGRATOR_ALLOWED_TOOLS` whitelist, including commands like `sessions send`, `channels publish`, `todo validate`, and other worker-wide surfaces.

The plan must switch from broadening `_SYS_ALL` to selective CommandAuth updates that mirror the integrator whitelist exactly.

## Important

### 2. Test paths are underspecified and grounding metadata is incomplete

Tasks 4, 5, and 7 say tests will be added in a "new or existing" test file, but the plan does not name the concrete test modules. `state.yaml.grounding.referenced_paths` also omits those test targets, which breaks the review-plan requirement that referenced paths cover all files named by the plan for staleness detection.

The plan needs concrete test paths for:

- API `sessions/run` metadata derivation coverage
- CLI `sessions list --job` handling
- integration bridge spawn-guard and `sessions run` spawning

Then `state.yaml.grounding.referenced_paths` must be updated to include those exact test files.

## Verdict

**NEEDS WORK** — 1 Critical, 1 Important.
