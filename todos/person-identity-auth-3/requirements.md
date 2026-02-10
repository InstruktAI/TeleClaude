# Requirements: Person Identity Auth — Phase 3: Role Gating & Adapter Integration

## Goal

Wire human role filtering into tool gating, integrate identity resolution into web/TUI/MCP boundaries, and add client auth command support with token issuance endpoint.

## Scope

### In scope

1. **Human role tool gating** — `HUMAN_ROLE_EXCLUDED_TOOLS` dict and filtering functions in role_tools.py.
2. **MCP wrapper human identity marker** — read/write `teleclaude_human_identity` marker file alongside existing `teleclaude_role`.
3. **Web boundary identity normalization** — headers to internal metadata mapping.
4. **Client auth command** — obtain bearer token for API calls; storage remains client-managed.
5. **Token issuance endpoint** — `POST /auth/token` on daemon API (Unix socket only).
6. **Integration tests** covering full identity + binding + gating flows.

### Out of scope

- Identity model (phase 1).
- Session binding and middleware (phase 2).
- Login UI / email OTP (web-interface todo).
- Telegram identity migration.

## Functional Requirements

### FR1: Human role tool gating

- `HUMAN_ROLE_EXCLUDED_TOOLS` dict mapping role → set of excluded tool names.
- Admin: no restrictions. Member: exclude deploy, remote session termination, agent availability mutation. Contributor: member limits plus no agent spawning or dependency/phase mutation. Newcomer: read-only tools only.
- `get_human_role_excluded_tools(role)` and `filter_tools_by_human_role(role, tools)` functions.

### FR2: MCP wrapper identity marker

- Write `teleclaude_human_identity` file to session TMPDIR (JSON: email, role, username).
- Read marker during tool filtering.
- Apply both AI role filter and human role filter.

### FR3: Web boundary normalization

- Headers `X-TeleClaude-Person-Email`, `X-TeleClaude-Person-Role`, optional `X-TeleClaude-Person-Username` normalized to internal metadata before session binding.

### FR4: Client auth command

- Client validates identity input and calls `POST /auth/token` on daemon to get signed token.
- Subsequent API calls include `Authorization: Bearer <token>`.
- Token persistence is client-managed; daemon host token files are forbidden.

### FR5: Token issuance endpoint

- `POST /auth/token` on daemon API (Unix socket only — trusted local process).
- Accepts email (and optional username).
- Issues signed token via `create_auth_token()`.

## Acceptance Criteria

1. Human role tools filtered correctly per role level.
2. MCP wrapper reads human identity marker and applies role filter.
3. Client bearer token flow works; API calls authenticated.
4. Newcomer can't start sessions; admin unrestricted.
5. Web boundary headers map to internal session metadata.
6. Integration tests cover full flow: config → resolver → binding → gating.

## Dependencies

- **person-identity-auth-2** must be complete (provides session binding, middleware, token utility).
