# Implementation Plan: Person Identity & Authentication

## Objective

Build daemon-side identity infrastructure: config model, resolver, session binding,
auth middleware, token utility, human role gating, and adapter integration.

This todo is split into 3 sub-todos that can be built sequentially.

---

## Sub-todo 1: Identity Model & Config (`person-identity-auth-1`)

Foundation: PersonEntry model, identity resolver, and config parsing.

### Task 1.1: Consume canonical PersonEntry schema from config validation

**Files:** `teleclaude/config/schema.py` and `teleclaude/core/identity.py`

Do not redefine `PersonEntry` in this todo. Reuse the validated model from
`teleclaude/config/schema.py` created by `config-schema-validation`.

Keep people schema in a single place and avoid model drift.

**Verification:** Unit test that validates identity resolver construction from
typed `GlobalConfig.people`.

### Task 1.2: Reuse config loader (no new YAML parser)

**Context:** People config lives in `~/.teleclaude/teleclaude.yml` (global level),
NOT in `config.yml` (daemon config). The daemon's `config.py` loads `config.yml`.
People must be loaded from the global teleclaude.yml separately.

**Files:** `teleclaude/core/identity.py` and `teleclaude/config/loader.py` (existing)

Create identity bootstrap logic that:

1. Calls `load_global_config()` from `teleclaude/config/loader.py`.
2. Reads `global_config.people` from the validated model.
3. Exposes a module-level `get_identity_resolver() -> IdentityResolver` function.

**Note:** No new YAML loading or parsing logic is allowed in this todo.

### Task 1.3: Identity resolver service

**File:** `teleclaude/core/identity.py` (same file as loader)

```python
@dataclass
class IdentityContext:
    email: str
    role: str
    username: str | None
    resolution_source: str  # "email", "username", "header", "token"

class IdentityResolver:
    def __init__(self, people: list[PersonEntry]):
        self._by_email: dict[str, PersonEntry] = ...
        self._by_username: dict[str, PersonEntry] = ...

    def resolve_by_email(self, email: str) -> IdentityContext | None: ...
    def resolve_by_username(self, username: str) -> IdentityContext | None: ...
```

Singleton resolver initialized at daemon startup from validated global config loaders.

### Task 1.4: Role constants

**File:** `teleclaude/constants.py`

Add human role constants:

```python
HUMAN_ROLE_ADMIN = "admin"
HUMAN_ROLE_MEMBER = "member"
HUMAN_ROLE_CONTRIBUTOR = "contributor"
HUMAN_ROLE_NEWCOMER = "newcomer"
HUMAN_ROLES = {HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER}
```

### Task 1.5: Unit tests

**File:** `tests/unit/test_identity.py`

- PersonEntry parsing from dict.
- Role validation (valid roles pass, invalid raises).
- IdentityResolver: lookup by email and username.
- IdentityResolver: unknown signals return None.
- IdentityContext dataclass construction.

---

## Sub-todo 2: Session Binding & Auth Middleware (`person-identity-auth-2`)

Depends on: `person-identity-auth-1`.

### Task 2.1: DB migration — session identity columns

**File:** New migration in `teleclaude/core/migrations/`

```sql
ALTER TABLE sessions ADD COLUMN human_username TEXT;
ALTER TABLE sessions ADD COLUMN human_email TEXT;
ALTER TABLE sessions ADD COLUMN human_role TEXT;
```

### Task 2.2: Session model update

**Files:**

- `teleclaude/core/db_models.py` — add `human_username: Optional[str] = None` and
  `human_email: Optional[str] = None` and `human_role: Optional[str] = None` to `Session` model.
- `teleclaude/core/models.py` — add same fields to `SessionSummary` dataclass.
- `teleclaude/api_models.py` — add same fields to `SessionSummaryDTO` and
  update `from_core()` mapper.

### Task 2.3: Session creation binding

**Files:**

- `teleclaude/core/command_handlers.py` — during session creation, if identity context
  is available in command metadata, set `human_email`, optional `human_username`, and `human_role` on the
  session record.
- `teleclaude/core/db.py` — ensure `create_session()` persists the new fields.

For child sessions: look up parent session's `human_email`/`human_role` (and optional username) via
`initiator_session_id` and inherit.

### Task 2.4: Token signing utility

**File:** New `teleclaude/auth/__init__.py` + `teleclaude/auth/tokens.py`

```python
def create_auth_token(email: str, role: str, ttl_days: int = 30, username: str | None = None) -> str: ...
def verify_auth_token(token: str) -> IdentityContext | None: ...
```

Uses PyJWT with HS256. Secret from `TELECLAUDE_AUTH_SECRET` env var.
Claims: `sub` (email), `role`, optional `username`, `iat`, `exp`, `iss`.

**Dependency:** Add `PyJWT>=2.8.0` to `pyproject.toml`.

### Task 2.5: Auth middleware

**File:** `teleclaude/api_server.py`

Add middleware in `APIServer._setup_routes()` after existing `_track_requests`:

```python
@self.app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # 1. Check X-TeleClaude-Person-Email + X-TeleClaude-Person-Role (+ optional username header)
    # 2. Check Authorization: Bearer <token>
    # Attach IdentityContext to request.state.identity
    # Enforce 401/403 on non-public routes
    ...
```

Exempt paths: `/health`, `/ws`.

No permissive mode in this todo. This is greenfield strict enforcement.

### Task 2.6: Unit tests

**File:** `tests/unit/test_auth_tokens.py`

- Token creation and verification round-trip.
- Expired token rejected.
- Bad secret rejected.
- Missing claims rejected.

**File:** `tests/unit/test_session_binding.py`

- Session created with identity gets human_email/human_role (and optional username) set.
- Child session inherits parent's identity.
- Requests without identity are rejected on non-public routes.

---

## Sub-todo 3: Role Gating & Adapter Integration (`person-identity-auth-3`)

Depends on: `person-identity-auth-2`.

### Task 3.1: Human role tool gating

**File:** `teleclaude/mcp/role_tools.py`

Add parallel human role filtering:

```python
HUMAN_ROLE_EXCLUDED_TOOLS: dict[str, set[str]] = {
    HUMAN_ROLE_ADMIN: set(),  # no restrictions
    HUMAN_ROLE_MEMBER: {
        "teleclaude__deploy",
        "teleclaude__mark_agent_unavailable",
        "teleclaude__end_session",  # only own sessions
    },
    HUMAN_ROLE_CONTRIBUTOR: {
        "teleclaude__deploy",
        "teleclaude__mark_agent_unavailable",
        "teleclaude__end_session",
        "teleclaude__start_session",
        "teleclaude__run_agent_command",
        "teleclaude__set_dependencies",
        "teleclaude__mark_phase",
    },
    HUMAN_ROLE_NEWCOMER: {
        # Read-only surface only; block all mutating teleclaude operations
        "teleclaude__start_session",
        "teleclaude__send_message",
        "teleclaude__run_agent_command",
        "teleclaude__end_session",
        "teleclaude__deploy",
        "teleclaude__mark_phase",
        "teleclaude__set_dependencies",
        "teleclaude__mark_agent_unavailable",
    },
}

def get_human_role_excluded_tools(human_role: str | None) -> set[str]: ...
def filter_tools_by_human_role(human_role: str | None, tools: list[ToolSpec]) -> list[ToolSpec]: ...
```

### Task 3.2: MCP wrapper human identity marker

**File:** `teleclaude/entrypoints/mcp_wrapper.py`

Add `_read_human_identity_marker()` alongside existing `_read_role_marker()`.
Reads `teleclaude_human_identity` file from session TMPDIR (JSON: `{"email": "...", "role": "...", "username": "..."}`).

During tool filtering, apply BOTH:

1. AI role filter (existing `filter_tool_specs`)
2. Human role filter (new `filter_tools_by_human_role`)

Write human identity marker during session creation (same flow that writes `teleclaude_role`).

### Task 3.3: Boundary identity integration (no Telegram changes in this todo)

**Files:**

- web boundary adapter/proxy integration path
- `teleclaude/entrypoints/mcp_wrapper.py`
- TUI CLI/auth client path

Ensure inbound identity is normalized to `{email, role, username?}` before
session binding and authorization checks.

### Task 3.4: Client auth command

**File:** New command or extension in TUI CLI.

Client auth flow:

1. Validate email exists in people config via identity resolver.
2. Call daemon API to issue a signed token.
3. Return token to caller; persistence is client-managed and out of daemon scope.
4. Subsequent client API calls include `Authorization: Bearer <token>`.

**File:** `teleclaude/api_server.py` — add `POST /auth/token` endpoint:

- Accepts email (and optional username) from request (Unix socket only — trusted local process).
- Issues signed token via `create_auth_token()`.
- Returns token in response.

### Task 3.5: Integration tests

**File:** `tests/integration/test_identity_integration.py`

- Full flow: config with people → identity resolver → session creation with binding.
- Header-based auth: email/role headers -> session has identity.
- Token issuance → API call with token → middleware resolves identity.
- Child session inherits parent identity.
- Role gating: restricted tool blocked for contributor/newcomer.

---

## Risks

1. **PyJWT dependency** — new dependency. Low risk (mature, widely used, minimal footprint).
2. **Header trust boundary** — must only accept identity headers from trusted web boundary.
3. **DB migration on production** — ALTER TABLE ADD COLUMN is safe for SQLite (no downtime).
4. **Strict auth rollout** — unauthenticated calls to non-public routes will now fail by design.

## Exit Criteria

1. PersonEntry with email + role parsed from global teleclaude.yml.
2. Identity resolver maps email and username to person.
3. Sessions have human_email, human_role, and optional human_username columns.
4. Auth middleware attaches identity context on API requests.
5. Human role filtering blocks restricted tools.
6. Web/TUI/MCP boundaries provide normalized identity consumed by the daemon.

## Required Input Artifact

- `docs/third-party/assistant-ui/index.md` (JWT choice, replay constraints, key rotation).
