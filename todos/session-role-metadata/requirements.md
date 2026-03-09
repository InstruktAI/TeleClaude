# Requirements: session-role-metadata

## Goal

Fix the integrator spawn guard by introducing `integrator` as a first-class session permission profile and adding structured `job` metadata to sessions. The current guard relies on title text, so dead sessions can appear active and block new integrator spawns indefinitely. Structured identity must make integrator detection queryable and reliable.

## Scope

### In scope

- Extend the existing system-role model so `integrator` is recognized consistently across shared constants, session-role derivation, clearance enforcement, and CLI command-auth metadata.
- Define an integrator permission profile using the existing clearance-gated tool policy pattern. The profile must allow the integrator to observe relevant sessions and operations, report results, and advance integration, while preventing it from dispatching sessions or performing orchestrator/planning actions.
- Ensure command-driven session creation derives structured session identity server-side from the invoked slash command, storing both a system role and a job label in session metadata for worker lifecycle commands and the integrator command.
- Route integrator spawning through the same command-driven session creation flow used by other slash-command launches so integrator identity is derived by the server rather than injected by the caller.
- Add job-based session filtering to the existing session listing surface (API plus `telec sessions list`) so callers can request sessions by `session_metadata.job`.
- Replace the integrator singleton guard's title-text check with a structured query for open sessions whose `session_metadata.job` is `integrator`.
- Keep CLI help/auth metadata aligned with the runtime permission model so integrator-accessible commands remain accurately documented and authorized.

### Out of scope

- Changing worker or orchestrator permissions beyond the minimum harmonization needed to introduce integrator
- TUI or frontend changes
- Caller-supplied `system_role` or `job` values
- Backfilling existing session rows that lack `job` metadata `[inferred]`

## Success criteria

- [ ] Targeted automated coverage is added or updated for:
  - role-based tool access and command-auth behavior for integrator sessions
  - server-side session-role/job derivation for command-driven session creation
  - session-list job filtering in the API/CLI path
  - integrator spawn-guard behavior in the integration bridge
- [ ] Relevant targeted tests pass for the touched areas, and the normal verification path for the change set remains green
- [ ] `telec sessions run --command /next-integrate --project .` creates a session whose metadata includes `system_role == "integrator"` and `job == "integrator"`
- [ ] `telec sessions run --command /next-build --args test-slug --project .` creates a session whose metadata includes `system_role == "worker"` and `job == "builder"`
- [ ] `telec sessions list --all --job integrator` returns only sessions whose `session_metadata.job == "integrator"`
- [ ] The `job` filter narrows the existing session visibility rules rather than bypassing them; existing initiator-scoping, `--all`, `--closed`, and role-based visibility behavior continue to work `[inferred]`
- [ ] An integrator session receives HTTP 403 when calling `telec todo work`
- [ ] An integrator session can call `telec todo integrate` successfully
- [ ] Killing the active integrator tmux pane and queueing a new candidate results in a new integrator session spawning instead of the dead session blocking the queue
- [ ] CLI help for the changed session-listing surface documents the new `--job` filter, and any documented session metadata flags continue to match implemented behavior `[inferred]`

## Constraints

- Metadata derivation for `system_role` and `job` is strictly server-side; callers must not be able to override either field.
- Python state-machine operations that execute inside `integration/state_machine.py` bypass the clearance system and must not be treated as integrator-allowed agent tools.
- The integrator remains a singleton queue drainer; any open session with `job=integrator` must block spawning a second integrator.
- The new job filter must compose with the existing local-plus-cache session merge path instead of introducing a separate visibility path `[inferred]`

## Risks

- Legacy open integrator sessions created before this change may not carry `job` metadata, so the structured guard may briefly miss them and allow one duplicate integrator to coexist until the old session closes `[inferred]`
