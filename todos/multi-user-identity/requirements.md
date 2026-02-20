# Requirements: OS User Identity Resolution

## Goal

Enable the daemon to resolve a connecting Unix socket client's OS user to a TeleClaude person and role. This is the authentication layer for local multi-user access — the kernel tells the daemon who is connecting.

## Problem Statement

The MCP socket (`/tmp/teleclaude.sock`) accepts connections without caller authentication. The TUI assumes the person at the terminal is the admin. Any local process can connect and execute any command. In a multi-user deployment, the daemon must know WHO is connecting to enforce role-based access.

## In Scope

1. **PersonEntry extension** — Add `os_username: Optional[str]` field to map OS users to TeleClaude persons.
2. **Socket peer credential extraction** — Platform-specific module to get UID from Unix socket connections (`SO_PEERCRED` on Linux, `LOCAL_PEERCRED` on macOS).
3. **Identity resolution pipeline** — UID → OS username (`pwd.getpwuid`) → PersonEntry lookup → CallerIdentity (person name + role).
4. **Unknown UID fallback** — Connections from unmapped OS users get `public` role (least privilege).
5. **Command context injection** — Resolved identity passed through the command pipeline alongside `caller_session_id`.
6. **Platform abstraction** — Clean interface that works on both macOS and Linux.

## Out of Scope

- Session ownership columns (Phase 2: `multi-user-sessions`).
- Config separation (Phase 4: `multi-user-config`).
- Service user creation (Phase 5: `multi-user-service`).
- External adapter identity changes — Telegram/Discord continue resolving identity via chat ID → person → role. No changes needed.
- HTTP API authentication — TUI connects via HTTP to API server; identity injection for HTTP is a separate concern from socket auth.

## Success Criteria

- [ ] Given a Unix socket connection, daemon extracts peer UID via platform-specific API.
- [ ] UID maps to OS username via `pwd.getpwuid()`.
- [ ] OS username matches `PersonEntry.os_username` → resolved person and role.
- [ ] Unknown UID (no matching PersonEntry) → `CallerIdentity` with role `"public"`.
- [ ] Resolved identity injected into command context for downstream handlers.
- [ ] Works on macOS (LOCAL_PEERCRED) and Linux (SO_PEERCRED).
- [ ] Existing external adapter identity flows are unaffected.
- [ ] Unit tests cover: credential extraction, person resolution, unknown-UID fallback.
- [ ] Integration test: mock socket with peer credentials → identity resolved correctly.

## Constraints

- The existing `PersonEntry.username` field is a general display name, NOT the OS username. The new `os_username` field is explicitly for OS user mapping.
- Must not require configuration changes for single-user installs — `os_username` is optional.
- Socket credential APIs are kernel-level and well-established, but the Python stdlib surface differs between macOS and Linux. Platform detection via `sys.platform`.
- The MCP wrapper (`mcp_wrapper.py`) is a stdio proxy. Identity resolution should happen daemon-side when accepting the socket connection, not in the wrapper.

## Risks

- **macOS LOCAL_PEERCRED API surface**: Less documented than Linux SO_PEERCRED. Need to verify Python socket module support. Mitigation: targeted research spike before build.
- **Docker socket access**: Container processes connecting to a host socket may have unexpected UIDs. Mitigation: document this edge case; not a blocker for initial implementation.
- **Root processes**: Processes running as root (UID 0) need explicit handling — map to admin or reject. Decision: map UID 0 to admin if a PersonEntry with os_username matching root exists, otherwise public.

## Dependencies

- None. This phase has no dependency on database abstraction (Phase 0) — it only touches config schema and socket handling.
- PersonEntry config schema in `teleclaude/config/schema.py` is stable.

## Existing Infrastructure to Leverage

- `_filter_sessions_by_role()` in `teleclaude/api_server.py` already implements role-based filtering using HTTP headers. Phase 2 will extend this to use socket identity.
- `human_email` and `human_role` columns already exist on sessions (from help desk identity flow). The pattern of identity → session metadata is established.
- `PersonConfig` in `teleclaude/config/schema.py` already has `creds` (telegram, discord). Adding `os_username` follows the same identity-key pattern.
