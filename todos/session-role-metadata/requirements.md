# Requirements: session-role-metadata

## Goal

Fix the integrator spawn guard by introducing `integrator` as a first-class session permission profile and adding a structured `job` metadata field to sessions. The current guard uses a naive string match on session titles — dead sessions appear active and block new integrator spawns indefinitely. Structured identity (role + job) enables reliable, query-based detection.

## Scope

### In scope

- Add `ROLE_INTEGRATOR` constant alongside existing `ROLE_WORKER` / `ROLE_ORCHESTRATOR`
- Add `INTEGRATOR_ALLOWED_TOOLS` permission whitelist limiting integrator to observe-and-report operations
- Route integrator in `is_tool_allowed()` to enforce the new whitelist
- Recognize `integrator` as a valid system role in the auth layer's role-derivation logic
- Add `COMMAND_ROLE_MAP` in `api_server.py` mapping slash commands to `(system_role, job)` tuples, auto-injected at session creation
- Switch integration bridge from `telec sessions start` to `telec sessions run --command /next-integrate` so metadata is derived server-side from the command name
- Add `--job` filter parameter to `GET /sessions` API endpoint
- Add `get_sessions_by_metadata()` helper to DB layer for JSON-path-based session queries
- Add `--job` flag to `telec sessions list` CLI command
- Replace string-match spawn guard with structured `--job integrator` query
- Update CLI surface docs: `ROLE_INTEGRATOR` constant, `_SYS_INTEGRATOR` frozenset, `_SYS_ALL` extension, `CommandAuth` entries for integrator-accessible commands

### Out of scope

- Changes to existing worker or orchestrator permission profiles
- TUI or frontend changes
- Caller-injected metadata — `system_role` and `job` are always server-side derived
- Migrating legacy session records to backfill missing `job` values

## Success Criteria

- [ ] `make test` passes with all existing tests green
- [ ] `telec sessions run --command /next-integrate --project .` creates a session with `session_metadata.system_role == "integrator"` and `session_metadata.job == "integrator"` (verified via `telec sessions list --all --job integrator` returning the session)
- [ ] `telec sessions list --all --job integrator` returns only sessions where `session_metadata.job == "integrator"`
- [ ] An integrator session receives HTTP 403 when calling `telec todo work` [inferred: enforced by `is_tool_allowed()` whitelist]
- [ ] An integrator session receives HTTP 200 when calling `telec todo integrate`
- [ ] Killing the integrator tmux pane and queuing a new candidate results in a new integrator session spawning (zombie sessions no longer block)
- [ ] `telec sessions run --command /next-build --args test-slug --project .` creates a session with `system_role=worker, job=builder` in metadata

## Constraints

- Python state machine operations (`roadmap deliver`, `todo demo create`, `make restart`) execute inside `integration/state_machine.py` and bypass the clearance system — they must NOT appear in `INTEGRATOR_ALLOWED_TOOLS`
- Metadata derivation is strictly server-side; no caller-supplied `system_role` or `job` values are accepted
- Integrator is a singleton; the spawn guard must reject on any open session with `job=integrator`, not just title-matched sessions

## Risks

- Legacy open integrator sessions (created before this change) will not have `session_metadata.job`; the new `--job integrator` guard will not see them, potentially allowing a duplicate spawn to coexist briefly [inferred: acceptable transitional behavior — old sessions will eventually close naturally]
