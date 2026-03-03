# cli-authz-overhaul — Input

# CLI Authorization Overhaul — Comprehensive Input

## Vision

Consolidate all agent tooling authorization onto the self-describing telec CLI. The CLI's `CommandDef` entries become the single source of truth for authorization. The API dogfoods this. Role-filtered baselines are pre-computed by `telec sync` and injected at session start. No deny-lists — everything is allow-list. No unauthorized fallback — 401 or nothing.

## Two Authorization Axes (Intersection)

- **System role** (session type): `worker` | `orchestrator`. Binary. Mandatory on session creation. No heuristic, no derivation, fail fast.
- **Human role** (person identity): `admin` | `member` | `contributor` | `newcomer` | `customer`. NOT a linear hierarchy — customer is orthogonal. Admin bypasses all human-role checks.
- **Composition**: `allowed(cmd) = system_allows(cmd) AND (human_role == "admin" OR human_allows(cmd))`

## Workstream 1: Self-Describing CommandDef with Auth Metadata

Add `CommandAuth` to every `CommandDef` in `CLI_SURFACE` (telec.py):

```python
@dataclass
class CommandAuth:
    system: frozenset[str]   # allowed system roles
    human: frozenset[str]    # allowed human roles (admin always implicit)
```

Every leaf command gets an `auth` field. This is the ONLY source of truth for authorization. The full per-command matrix is in `docs/project/design/cli-authorization-matrix.md` (already produced).

Key corrections to apply from user feedback:
- `sessions escalate`: allowed for ALL non-admins (worker ✅, member ✅, contributor ✅, newcomer ✅, customer ✅). Admin ❌ (they ARE the target).
- `sessions end`: admin ✅, member ✅ (self-scoped at API layer). Nobody else.
- `sessions restart`: admin only.
- `sessions revive`: admin only.
- `sessions unsubscribe`: admin ✅, member ✅. Nobody below.
- `roadmap list`: worker ❌ (workers don't look around, they execute).
- Everything is ALLOW-LIST. Admin gets everything except escalate. Everyone else is explicitly listed.

Add `is_command_allowed(command, system_role, human_role) -> bool` function next to CLI_SURFACE. This is imported by the API for enforcement.

## Workstream 2: Kill Legacy Authorization Code

Delete entirely:
- `teleclaude/core/tool_access.py` — replaced by CommandAuth on CommandDef
- All `CLEARANCE_*` constants in `api/auth.py` — replaced by `is_command_allowed()`
- `WORKER_EXCLUDED_TOOLS`, `MEMBER_EXCLUDED_TOOLS`, `UNAUTHORIZED_EXCLUDED_TOOLS`, `CUSTOMER_EXCLUDED_TOOLS` — all gone
- `DEFAULT_UNIDENTIFIED_HUMAN_ROLE` — gone
- `_derive_session_system_role()` heuristic — gone

Replace `verify_caller()` fallback logic: if identity can't be resolved → 401. Hard. No fallback role, no default.

API routes use a new dependency that calls `is_command_allowed()` with the endpoint-to-command mapping.

## Workstream 3: Role-Aware `telec -h`

The help functions (`_usage_main`, `_usage_subcmd`, `_usage_leaf`) read the caller's role locally:
1. `TELECLAUDE_SYSTEM_ROLE` env var → system role (set by daemon at session creation)
2. Read telec login file → email → read `~/.teleclaude/teleclaude.yml` people section → map to human role
3. Filter CLI_SURFACE: only show commands where `is_command_allowed()` returns True
4. Render filtered output

Zero API calls. Works even if daemon is down. Self-describing.

## Workstream 4: Mandatory Session Fields / Fail Fast

`system_role` is MANDATORY on session creation. No heuristic derivation. `_derive_session_system_role()` gets deleted. Session creation API/code fails if `system_role` is not provided.

`human_role` is also mandatory — everyone is authenticated now.

Session bootstrap injects `TELECLAUDE_SYSTEM_ROLE` as tmux env var for CLI to read.

Review all session creation paths (API, adapters, CLI `sessions start/run`) to ensure both fields are always provided.

## Workstream 5: Role-Specific Baseline Generation (telec sync)

`telec sync` generates pre-computed role-filtered CLI reference files:
- One per effective role profile (admin, member, contributor, newcomer, customer × worker/orchestrator — but many combinations collapse)
- Uses the same `is_command_allowed()` function to filter
- Output: rendered help text showing only allowed commands for that role
- Files placed at a known location for session-start injection

Remove the static CLI spec from the baseline doc chain:
- `docs/global/general/spec/tools/telec-cli.md` — remove `<!-- @exec: telec -h -->` directives (or move them to the role-aware generator)
- `docs/global/baseline.md` — remove the telec-cli.md reference
- The inflated AGENTS.md no longer contains the CLI surface statically

## Workstream 6: Session-Start Context Injection

At session bootstrap, the daemon:
1. Knows the session's (system_role, human_role) — both mandatory
2. Picks the appropriate pre-computed role-filtered baseline
3. Writes it to a fixed session-specific path or injects it via the existing context injection mechanism

GAP: The exact last-mile mechanism needs discovery. How does a dynamically-written file get into the agent's system prompt? Options: fixed-path file referenced by hook, tmux env var pointing to file, or Claude Code system-prompt hook. The prepare phase should investigate the existing session context injection and propose the cleanest path.

## Workstream 7: New CLI Commands for Uncovered API Routes

These API routes have no CLI command counterpart. Need new CommandDefs with proper CommandAuth:

### `telec todo list`
- Maps to: `GET /todos`
- Type: R
- Auth: worker ❌, orchestrator ✅, admin ✅, member ✅, contributor ✅, newcomer ✅, customer ❌

### `telec jobs list`
- Maps to: `GET /jobs`
- Type: R
- Auth: worker ❌, orchestrator ✅, admin ✅, member ✅, contributor ❌, newcomer ❌, customer ❌

### `telec jobs run <name>`
- Maps to: `POST /jobs/{name}/run`
- Type: W
- Auth: worker ❌, orchestrator ✅, admin ✅, member ❌, contributor ❌, newcomer ❌, customer ❌

### `telec jobs create`
- Maps to: new API endpoint needed
- Type: W
- Auth: worker ❌, orchestrator ✅, admin ✅, member ✅, contributor ❌, newcomer ❌, customer ❌
- GAP: Job schema and creation flow need design. What fields? Cron expression? Handler?

### `telec config settings get`
- Maps to: `GET /settings`
- Type: R
- Auth: worker ❌, orchestrator ✅, admin ✅, member ✅, contributor ❌, newcomer ❌, customer ❌
- Fold runtime settings under `telec config` namespace

### `telec config settings patch`
- Maps to: `PATCH /settings`
- Type: W
- Auth: worker ❌, orchestrator ✅, admin ✅, member ✅ (own settings), contributor ❌, newcomer ❌, customer ❌

### Notifications (new top-level `telec notifications` namespace):
- `telec notifications list` — R, worker ❌, orch ✅, admin ✅, member ✅, contributor ❌, newcomer ❌, customer ❌
- `telec notifications get <id>` — R, same as list
- `telec notifications seen <id>` — W, admin ✅, member ✅
- `telec notifications claim <id>` — W, admin ✅, member ✅
- `telec notifications status <id>` — W, admin ✅
- `telec notifications resolve <id>` — W, admin ✅

GAP: Exact notification auth needs review during prepare. Workers may need notification access for their own session's notifications.

## Workstream 8: Cover All API Routes with Clearance

Every API route must have a CLEARANCE dependency. The new model: API maps endpoint to CLI command name, calls `is_command_allowed()`. Routes that currently lack clearance:
- `GET /api/people` → mapped to `telec config people list`
- `GET/PATCH /settings` → mapped to `telec config settings get/patch`
- `GET /jobs`, `POST /jobs/{name}/run` → mapped to `telec jobs list/run`
- `GET /todos` → mapped to `telec todo list`
- All `/api/notifications/*` → mapped to `telec notifications *`

No route in the system should be unprotected. Default-deny for unmapped routes.

## Workstream 9: Project Ownership Model & teleclaude.yml Consolidation

### Kill projects.yaml
- Migrate project registry into `teleclaude.yml`
- Global `~/.teleclaude/teleclaude.yml` gets a `projects:` section
- Per-person `~/.teleclaude/people/{name}/teleclaude.yml` gets a `projects:` section for member-created projects

### Directory scoping
- Members' project directories live under their person folder: `~/.teleclaude/people/{name}/projects/{project-name}/`
- `telec init` enforces: if caller is member, current directory must be under their folder. If admin, anywhere.
- Admin can assign existing projects to members via the global config people entries (e.g., `allowed_projects: [project-slug, ...]`)

### Scanner signal
- If a directory has `teleclaude.yml`, it's a wired-up project. That's the scanner signal.
- No more multiple config file names. `teleclaude.yml` is THE signal.

### Policy
- Agents NEVER create new YAML config files. `teleclaude.yml` is the only config file. Period. This should be codified as a policy doc snippet.

GAP: Schema for the `projects:` section in teleclaude.yml needs design. Fields: name, path, description, owner, access list. The prepare phase should propose this.

## Workstream 10: Documentation Updates

These docs are stale and need updating:
- `project/spec/identity-and-auth.md` — references unauthorized fallback, needs to reflect mandatory auth
- `project/spec/command-surface.md` — incomplete command list, no auth metadata, needs to reflect self-describing model
- `general/spec/tools/telec-cli.md` — the `<!-- @exec -->` pattern changes to role-aware generation
- `docs/global/baseline.md` — CLI spec reference extraction
- `docs/global/baseline-progressive.md` — may need role-specific variants

New docs needed:
- Policy: "agents never create config files"
- Design: self-describing CLI authorization model
- Spec: updated command surface with auth metadata

## Workstream 11: Update the Authorization Matrix Artifact

The matrix at `docs/project/design/cli-authorization-matrix.md` needs corrections:
- Apply all user-confirmed corrections (sessions end member ✅, restart/revive admin-only, etc.)
- Add new commands (todo list, jobs list/run/create, config settings, notifications)
- Switch format from deny-list reasoning to allow-list declarations
- Ensure it stays in sync with CommandDef auth fields (ideally generated from them after workstream 1)

## Dependencies

- Workstream 1 (CommandAuth on CommandDef) is the foundation — everything else depends on it
- Workstream 2 (kill legacy) depends on 1 + 8 (API routes covered first)
- Workstream 3 (role-aware help) depends on 1
- Workstream 4 (mandatory fields) depends on nothing — can start immediately
- Workstream 5 (baseline generation) depends on 1 + 3
- Workstream 6 (session injection) depends on 5, needs discovery
- Workstream 7 (new CLI commands) depends on 1
- Workstream 8 (API coverage) depends on 1 + 7
- Workstream 9 (project ownership) is mostly independent, depends on 4 for mandatory fields
- Workstream 10 (docs) depends on all other workstreams being at least designed
- Workstream 11 (matrix update) depends on 1 + 7

## Open Gaps for Prepare Phase

1. Session-start context injection last-mile mechanism (workstream 6)
2. Job creation schema and API endpoint design (workstream 7)
3. Notification CLI auth for workers accessing own-session notifications (workstream 7)
4. teleclaude.yml projects section schema (workstream 9)
5. Runtime settings: confirm fold into `telec config settings` vs separate namespace (workstream 7)
6. Role-specific baseline file naming and output location (workstream 5)
7. All session creation paths audit for mandatory field enforcement (workstream 4)
