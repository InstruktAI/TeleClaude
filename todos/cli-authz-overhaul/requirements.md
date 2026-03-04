# Requirements: cli-authz-overhaul

## Goal

Make the CLI's `CommandDef` entries the single source of truth for authorization by adding
`CommandAuth` metadata to every leaf command and providing an `is_command_allowed()` function.
This is the foundation that all subsequent authorization workstreams depend on.

The full authorization overhaul vision spans 11 workstreams (see `input.md`). This todo
delivers **Workstream 1** only: the self-describing CommandDef with auth metadata. All other
workstreams become follow-on todos that depend on this one.

## Scope

### In scope

1. **`CommandAuth` dataclass** — added to `telec.py` alongside `CommandDef`.
   - `system: frozenset[str]` — allowed system roles (`worker`, `orchestrator`).
   - `human: frozenset[str]` — allowed human roles. Admin is always implicitly allowed
     (except for `sessions escalate` where admin is explicitly excluded).
   - Admin-implicit convention: when checking `is_command_allowed()`, admin bypasses the
     human-role check unless admin is explicitly in an `exclude_human` set.

2. **`auth` field on `CommandDef`** — optional at the type level (parent group nodes don't
   need auth), but every leaf command in `CLI_SURFACE` must have it populated.

3. **`is_command_allowed(command_path, system_role, human_role) -> bool`** — the canonical
   authorization check function. Lives in `telec.py` next to `CLI_SURFACE`. Imported by
   `api/auth.py` for API enforcement.
   - `command_path`: dot-separated or space-separated path (e.g., `"sessions.start"` or
     `"telec sessions start"`).
   - Composition: `allowed = system_allows(cmd) AND (human_role == "admin" OR human_allows(cmd))`.
   - Special case: `sessions escalate` — admin is explicitly excluded (admin IS the target).

4. **Populate auth metadata** on every leaf command, using the corrected authorization matrix:
   - Apply user-confirmed corrections (see Corrections section below).
   - Ensure consistency with `docs/project/design/cli-authorization-matrix.md`.

5. **Update `cli-authorization-matrix.md`** to reflect corrections and align with code.

### Out of scope (follow-on todos)

- WS2: Kill legacy `tool_access.py` deny-lists and `CLEARANCE_*` constants.
- WS3: Role-aware `telec -h` (filter help output by caller role).
- WS4: Mandatory `system_role`/`human_role` on session creation; kill `_derive_session_system_role()`.
- WS5: Role-specific baseline generation via `telec sync`.
- WS6: Session-start context injection of role-filtered baselines.
- WS7: New CLI commands for uncovered API routes (todo list, jobs, settings, notifications).
- WS8: Cover all API routes with clearance using the new model.
- WS9: Project ownership model and `teleclaude.yml` consolidation.
- WS10: Documentation updates.

## User-Confirmed Corrections to Authorization Matrix

These corrections override the existing matrix document where they differ:

| Command | Correction | Rationale |
|---|---|---|
| `sessions end` | admin ✅, member ✅ (self-scoped at API layer) | Members can end their own sessions. |
| `sessions restart` | admin only | Restarting sessions is admin infrastructure. |
| `sessions revive` | admin only | Reviving dead sessions is admin infrastructure. |
| `sessions escalate` | ALL non-admins ✅, admin ❌ | Admin is the escalation target, not the source. Workers MUST be able to escalate. |
| `roadmap list` | worker ❌ | Workers execute, they don't look around at planning. |

## Success Criteria

- [ ] Every leaf command in `CLI_SURFACE` has a populated `auth: CommandAuth` field.
- [ ] `is_command_allowed()` exists and correctly implements the two-axis composition rule.
- [ ] `is_command_allowed()` returns the correct result for every (command, system_role, human_role) combination in the authorization matrix.
- [ ] Unit tests cover: admin bypass, admin escalate exclusion, worker restrictions, member restrictions, contributor restrictions, newcomer restrictions, customer restrictions.
- [ ] `cli-authorization-matrix.md` is updated with user-confirmed corrections.
- [ ] No changes to existing runtime behavior — the new code is additive. Legacy `tool_access.py` and `CLEARANCE_*` constants are untouched (they will be replaced in WS2/WS8).

## Constraints

- The `CommandAuth` metadata must be co-located with `CLI_SURFACE` in `telec.py` — it is the source of truth.
- Admin is always implicitly allowed for human-role checks, EXCEPT `sessions escalate`.
- The `is_command_allowed()` function must be importable by `api/auth.py` without circular imports.
- Do not modify `tool_access.py` or `api/auth.py` behavior — those are WS2/WS8.

## Risks

- **Circular import**: `is_command_allowed()` in `telec.py` imported by `api/auth.py`. Mitigate by ensuring `telec.py` does not import from `api/` or `core/`.
- **Matrix staleness**: If new commands are added to `CLI_SURFACE` without auth, enforcement breaks. Mitigate with a test that asserts every leaf command has `auth` populated.
- **Correction conflicts**: User corrections may conflict with matrix reasoning. Resolution: user corrections take precedence — the matrix is updated to match.
