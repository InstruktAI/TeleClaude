# Person Identity Auth — Phase 3: Role Gating & Adapter Integration

## Context

This is phase 3 of the person-identity-auth breakdown. Depends on phase 2
(session binding and auth middleware). See the parent todo's
`implementation-plan.md` for full architectural context.

## Intended Outcome

Wire human role filtering into tool gating, integrate identity resolution into
web/TUI/MCP boundaries, and add TUI login command.

## What to Build

1. **Human role tool gating** — extend `teleclaude/mcp/role_tools.py` with `HUMAN_ROLE_EXCLUDED_TOOLS` dict and filtering functions. Parallel to existing AI role filtering.
2. **MCP wrapper human identity marker** — in `teleclaude/entrypoints/mcp_wrapper.py`, add `teleclaude_human_identity` marker file read/write alongside existing `teleclaude_role`. Marker payload includes email, role, and optional username. Apply both AI and human role filters.
3. **Web boundary identity normalization** — ensure header-based identity is normalized to internal metadata (`human_email`, `human_role`, optional `human_username`) before authorization and binding paths.
4. **TUI login command** — `telec login <email>` validates against config, calls `POST /auth/token` on daemon, stores token at `~/.teleclaude/auth_token`.
5. **Token issuance endpoint** — `POST /auth/token` on daemon API (Unix socket only).
6. **Integration tests** covering full identity resolution + session binding + role gating flows.

## Key Architectural Notes

- MCP wrapper already has `_read_role_marker()` at line 190 and `_write_role_marker()` at line 225 — follow same pattern for human identity.
- role_tools.py currently has a single `WORKER_EXCLUDED_TOOLS` set. Human roles use a dict mapping role → excluded tools.
- The `POST /auth/token` endpoint is Unix-socket-only (trusted local process), so no auth check needed on the endpoint itself.

## Verification

- MCP: human identity marker written and read; human role tools filtered.
- TUI: `telec login user@example.com` stores token; API calls authenticated.
- Role gating: newcomer can't start sessions; admin unrestricted.
- Web boundary headers map consistently to internal session metadata.
