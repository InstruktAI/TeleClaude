---
id: 'project/spec/feature/agent_runtime/session-lifecycle'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'v1 agent_runtime — start, list, and end agent sessions over the HTTP API. The creation, enumeration, and explicit-termination surface that operators and other agents use.'
---

# Session Lifecycle — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The v1 surface for managing the live dimension of an `agent_runtime` Session: creating one (allocating a `session_id`, an associated tmux session, and a principal binding), listing what currently exists (subject to role-based visibility), and explicitly ending one (a request to transition to `closed`).

Three FastAPI routes form the surface, all backed by the in-process command service: `POST /sessions`, `GET /sessions`, and `DELETE /sessions/{session_id}`. The TUI invokes them via the `telec sessions start`, `telec sessions list`, and `telec sessions end` CLI verbs respectively. Remote-computer routing is not yet implemented — `request.computer` is logged but every session is created locally.

Termination accepted via the API is a request, not a finished close: `DELETE` returns `202 Accepted` and delegates the actual cleanup to the cleanup module (see `session-cleanup-and-reaping`).

## Canonical fields

### Behavioral contract

#### Creating a session — happy path

```
Given an authenticated caller has clearance `sessions_start`
And the request carries an `origin` (terminal or web) and an enabled `agent`
When the caller POSTs to /sessions with project_path, agent, thinking_mode, launch_kind
Then a session_id is generated as `str(uuid.uuid4())` (or accepted from the command when pre-supplied)
And a tmux_session_name is composed as `tc_<session_id>` (prefix `tc_`, full UUID)
And the Session row is inserted in `agent_runtime.sessions` with `lifecycle_status="initializing"` and a complete payload (computer_name, title, project_path, subdir, working_slug, human_email, human_role, principal, active_agent, thinking_mode)
And tmux session creation + agent CLI launch are kicked off asynchronously by the daemon bootstrap task (not on the request path)
And the response carries `status="success"`, `session_id`, `tmux_session_name`, and the resolved `agent`
```

#### Principal binding from identity

```
Given the request supplies `origin_metadata` (web or terminal email payload)
When `create_session` resolves identity via the identity resolver
Then `human_email` and `human_role` are populated from the identity context when not explicitly provided
And when an `initiator_session_id` references a parent session, missing fields (human_email, human_role, principal) are inherited from the parent
And a session creation without any resolved human_role AND no `system_role` raises ValueError — the request is rejected
```

#### Computer routing (v1)

```
Given the request specifies `computer = <remote>`
When the daemon receives the POST /sessions
Then the daemon logs the requested computer
And creates the session on the LOCAL machine regardless of the `computer` field
And no remote dispatch occurs — remote creation via API is not implemented in v1
```

#### Additional context propagation

```
Given the caller passes `message` in the create request
And `launch_kind` is `agent` (the default)
When `_build_launch_intent` runs
Then launch_kind is upgraded to `agent_then_message`
And the `SessionLaunchIntent` is built with `agent`, `thinking_mode`, and `message`
And the message is persisted on the launch intent and replayed into the tmux pane by the daemon bootstrap task once the agent CLI is ready
And `_extract_initiator_session_id` records the caller's session id so the spawned child can notify the initiator on stop (one-shot listener)
```

#### Initiator listener registration

```
Given the caller's session is non-web (initiator_session_id present and not `web:`-prefixed)
And `skip_listener_registration` is false
When the new Session row is created
Then a stop-listener is registered tying caller -> new session
And the caller's tmux_session_name is captured so completion notifications can route back
And if the caller has no tmux session, registration is skipped with a debug log
```

#### Listing sessions — caller-scoped default

```
Given the TUI calls GET /sessions without `?all=true`
And the request carries the `x-caller-session-id` header
When `list_sessions` runs
Then local sessions are loaded via `command_handlers.list_sessions(include_closed=query.include_closed)`
And cached remote sessions are merged in by session_id (local wins on conflict)
And the merged list is filtered to entries whose `initiator_session_id == x-caller-session-id`
And role-based filtering is then applied (see below)
And optional `job` filter narrows further
And `human_name` is enriched from the people config for each entry whose email matches
```

#### Listing sessions — role-based visibility

```
Given the web client sends identity headers `x-web-user-email` and `x-web-user-role`
When `_filter_sessions_by_role` applies
Then role `admin` sees every session
And role `member` sees their own sessions PLUS sessions with `visibility == "shared"`
And role `contributor` / `newcomer` / unknown sees only their own sessions (matched by `human_email`)
And requests without identity headers (TUI / tool clients) are NOT filtered by role — they see everything reachable
```

#### Ending a session — happy path

```
Given a caller with clearance `sessions_end` and ownership of the session
When the caller DELETEs /sessions/{session_id}
Then the route authorizes the caller via `check_session_access(require_owner=True)`
And builds a `CloseSessionCommand(session_id)`
And dispatches it through the command service
And returns HTTP 202 with body `{"status":"accepted","message":"Session <id> closing","completion_event":<event_name>}`
And the actual termination work (tmux kill, resource cleanup, lifecycle transition) is performed asynchronously by the cleanup module — see session-cleanup-and-reaping
```

#### Ending a missing or already-closed session

```
Given the supplied session_id does not exist in the database
When the close command runs
Then the inner termination returns False and is logged at debug
And the API path still returns 202 (the route does not pre-check existence)
And no error is surfaced to the caller for a missing session
```

```
Given the session_id exists but is already marked closed (closed_at is non-null)
When the close command runs
Then the cleanup module proceeds with resource cleanup for any straggling artifacts (channel delete, workspace rmtree, tmpdir delete) but skips the closing -> closed lifecycle write
And the API path returns 202 as usual
```

#### Direct-link sessions

```
Given the caller passes `direct=true` AND has a non-web caller session
When the new session is created
Then `_link_direct_sessions` resolves both endpoints (titles, computer names, fallback to ids)
And `create_or_reuse_direct_link` materialises the conversation link
And the launch intent's message is wrapped with the direct-conversation protocol header and rules block
And the conversation link operates orthogonally to stop-listener subscriptions
```

### Implementation pointers (v1)

- `teleclaude/api/sessions_routes.py`
  - `list_sessions` (route `GET /sessions`, line 466)
  - `create_session` (route `POST /sessions`, line 529)
  - `end_session` (route `DELETE /sessions/{session_id}`, line 596)
  - `_prepare_create_session` (line 397) — collects metadata, initiator id, launch intent
  - `_resolve_created_session_transport` (line 440) — ensures the response carries both `session_id` and `tmux_session_name`
  - `_build_launch_intent` (line 266) — resolves `SessionLaunchKind` (empty / agent / agent_then_message / agent_resume)
  - `_filter_sessions_by_role` (line 89) — role-based list filtering
  - `_resolve_origin` (line 188) — origin + caller_email + origin_metadata derivation
  - `_extract_initiator_session_id` (line 161) — initiator session resolution
  - `_link_direct_sessions` (line 340) — direct-conversation linkage
- `teleclaude/core/command_handlers/_session.py`
  - `create_session` (line 61) — command handler; allocates session*id, composes `tc*<session_id>` tmux name (line 89), inserts the DB row, registers initiator listener
  - `list_sessions` (line 268) — DB list + SessionSnapshot mapping
- `teleclaude/core/tmux_bridge/_session.py`
  - `ensure_tmux_session` (line 276) — single choke point, idempotent (returns True if session already exists)
  - `_create_tmux_session` (line 111) — detached `new-session` with the teleclaude-shell wrapper, per-session TMPDIR
- `teleclaude/core/session_cleanup.py` — `TMUX_SESSION_PREFIX = "tc_"` (line 40)
- CLI surface: `telec sessions start`, `telec sessions list`, `telec sessions end` — invoke the routes above

### Cross-context references

- **identity** — `_resolve_origin` + `get_identity_resolver()` resolve principal binding (human_email, human_role, person identity) for the Session aggregate.
- **config** — `config.computer.name`, `config.computer.tmux_binary`, `config.computer.help_desk_dir`, enabled agents and defaults flow in via `_resolve_enabled_agent` / `get_default_agent`.
- **session_mirrors** — downstream consumer of the session-lifecycle events emitted as the Session moves through `initializing -> active -> closed`. The lifecycle write here is the source of those events.
- **workflow** — orchestrators dispatched as child sessions via this surface receive completion notifications through the one-shot stop-listener wired during `create_session`.

## Known caveats

- **Tmux name in v1 is the full UUID, not a short id.** `tc_<full-uuid>` is the actual format; the v2-target domain spec phrases it as `tc_<session_id_short>` for readability, but no shortening occurs in v1.
- **Remote-computer routing is logged but unimplemented.** The `computer` field on `CreateSessionRequest` is recorded; v1 creates every session locally. The TUI compensates by maintaining a remote-cache merge in `list_sessions`.
- **Tmux + agent launch are off the request path.** `create_session` only inserts the DB row and returns; tmux creation and agent CLI launch happen on the daemon's bootstrap task after the API has already responded with 200. Callers polling for tmux readiness must check downstream — this surface does not block until the pane is alive.
- **`ensure_tmux_session` is silently idempotent.** A name collision returns success without recreating — uniqueness is statistical (UUID4) rather than enforced by an explicit precheck. The v2-target "daemon refuses to start a session whose tmux name collides" is not a v1 behaviour; v1 simply joins the existing tmux session if one with the same name already exists.
- **`DELETE /sessions/{id}` is fire-and-forget.** 202 means "accepted for processing", not "closed". The caller does not learn the outcome of cleanup over this route; observing the `completion_event` (returned in the 202 body) or polling `GET /sessions?closed=true` is required.
- **Listing without identity headers reveals everything.** TUI and tool clients are intentionally unfiltered. Role-based gating is only applied when the web headers (`x-web-user-email`, `x-web-user-role`) are present. The `x-caller-session-id` header is what trims a tool-client's default view to caller-scoped — `?all=true` opts out.
- **Non-admin non-system-role sessions are jailed to the help-desk directory.** When the request has no `system_role` and the human role is anything other than admin, the project_path is forcibly replaced with the configured help-desk directory and `subfolder` / `working_slug` are cleared. This is policy, not failure.
- **`closed_at` is set by the cleanup module, not this surface.** This route only enqueues; see `session-cleanup-and-reaping` for the lifecycle field transitions and `agent_runtime.session.ended` payload.
- **v2-target framings deliberately not covered here:** `windowed-batch-write-and-dispatch`, three-lane signal coordination, `SessionRuntime` actor model, adaptive cadence, agent CLI hook reception via `telec-hook` — those describe target shape, not the v1 route surface documented in this snippet.
