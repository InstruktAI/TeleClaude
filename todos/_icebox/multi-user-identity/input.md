# OS User Identity Resolution

## Origin

Extracted from `multi-user-system-install` Phase 1. The multi-user project needs the daemon to know WHO is connecting. Unix socket peer credentials provide kernel-level authentication — no passwords, no tokens.

## What We Have Today

- `PersonEntry` in config schema has: name, identity keys (telegram_user_id, discord_user_id), role
- No `os_username` field in PersonEntry
- MCP socket (`/tmp/teleclaude.sock`) accepts connections without caller authentication
- `mcp-wrapper.py` injects `caller_session_id` from environment, but no identity/role
- External adapters (Telegram, Discord) resolve identity via chat ID → person → role
- TUI assumes the person at the terminal is the admin

## What Needs to Change

### 1. PersonEntry Extension

Add `os_username: Optional[str]` to `PersonEntry` config schema. Maps an OS user to a TeleClaude person.

### 2. Socket Peer Credential Resolution

When a client connects to the Unix socket:

1. Kernel provides peer's UID/GID via `SO_PEERCRED` (Linux) or `LOCAL_PEERCRED` (macOS)
2. Map UID → OS username (via `pwd.getpwuid()`)
3. Look up OS username in people config → resolve person + role
4. Unknown UID → `public` role (least privilege)

### 3. Platform Abstraction

Create `teleclaude/core/socket_auth.py`:

- `get_peer_uid(socket) -> int` — platform-specific credential extraction
- `resolve_caller_identity(uid, config) -> CallerIdentity` — UID to person/role
- `CallerIdentity` dataclass: person_name, role, os_username, uid

### 4. Integration Points

- MCP socket accept path: resolve identity on connection
- Inject `CallerIdentity` into command context alongside `caller_session_id`
- `mcp-wrapper.py`: pass identity info to daemon with each tool call
- TUI connection: resolve the terminal user's identity instead of assuming admin

### 5. External Adapters (No Change)

Telegram, Discord, email adapters continue resolving identity via their own identity keys. Socket auth is only for local Unix socket connections (MCP, TUI, API).

## Research Needed

- Python `socket` module: how to extract `SO_PEERCRED` on Linux
- Python `socket` module: how to extract `LOCAL_PEERCRED` on macOS
- Are there existing libraries that abstract this? (`python-ucred`, etc.)
- Edge cases: what UID does a Docker container process have when connecting to host socket?

## Dependencies

None. This phase has no dependency on the database abstraction — it only touches config schema and socket handling.
