# Implementation Plan: OS User Identity Resolution

## Overview

Add Unix socket peer credential resolution to the daemon so it knows which OS user is connecting. The approach uses kernel-level `SO_PEERCRED` (Linux) / `LOCAL_PEERCRED` (macOS) to extract the connecting process's UID, then maps it through the config to a TeleClaude person and role. Identity resolution happens daemon-side when accepting socket connections — the MCP wrapper remains a transparent proxy.

## Phase 1: Core Identity Module

### Task 1.1: Extend PersonEntry with os_username

**File(s):** `teleclaude/config/schema.py`

- [ ] Add `os_username: Optional[str] = None` to `PersonEntry`
- [ ] Ensure config validation allows the new field without breaking existing configs

### Task 1.2: Create socket_auth module

**File(s):** `teleclaude/core/socket_auth.py` (new)

- [ ] Define `CallerIdentity` dataclass:
  ```python
  @dataclass
  class CallerIdentity:
      person_name: str | None  # None for unknown/public
      role: str  # "admin", "member", "contributor", "newcomer", "public"
      os_username: str
      uid: int
  ```
- [ ] Implement `get_peer_uid(sock: socket.socket) -> int`:
  - macOS (`sys.platform == "darwin"`):
    - Use `sock.getsockopt(SOL_LOCAL, LOCAL_PEERCRED, struct_size)`
    - Parse `struct xucred` to extract `cr_uid`
    - `SOL_LOCAL = 0` and `LOCAL_PEERCRED = 0x001` on macOS
  - Linux:
    - Use `sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct_size)`
    - Parse `struct ucred` (pid, uid, gid) — uid at offset 4, 4 bytes
  - Raise `PeerCredentialError` on unsupported platforms
- [ ] Implement `resolve_caller_identity(uid: int, people: list[PersonEntry]) -> CallerIdentity`:
  - Map UID → OS username via `pwd.getpwuid(uid).pw_name`
  - Search people list for matching `os_username`
  - Match found → CallerIdentity with person's name and role
  - No match → CallerIdentity with role="public", person_name=None
- [ ] Implement `PUBLIC_IDENTITY` constant for the default unknown-user identity

### Task 1.3: Integrate into MCP backend socket accept

**File(s):** `teleclaude/mcp/server.py` (or wherever the daemon accepts Unix socket connections)

- [ ] On socket accept, call `get_peer_uid()` + `resolve_caller_identity()`
- [ ] Attach `CallerIdentity` to the connection/request context
- [ ] Pass identity through to tool call handlers

### Task 1.4: Inject identity into command context

**File(s):** `teleclaude/core/command_service.py`, `teleclaude/mcp/handlers.py`

- [ ] Extend command context to carry `caller_identity: CallerIdentity | None`
- [ ] MCP tool calls include the resolved identity
- [ ] Non-socket origins (Telegram, Discord) continue using their existing identity flow — `caller_identity` is None for adapter-originated commands

---

## Phase 2: Validation

### Task 2.1: Tests

**File(s):** `tests/unit/test_socket_auth.py` (new)

- [ ] Unit test: `get_peer_uid()` with mocked socket on current platform
- [ ] Unit test: `resolve_caller_identity()` with known PersonEntry → correct identity
- [ ] Unit test: `resolve_caller_identity()` with unknown UID → public role
- [ ] Unit test: `resolve_caller_identity()` with UID 0 (root) handling
- [ ] Unit test: PersonEntry without `os_username` → not matched by OS user lookup
- [ ] Integration test: mock socket connection → full identity resolution pipeline

### Task 2.2: Quality Checks

- [ ] Run `make test`
- [ ] Run `make lint`
- [ ] Verify existing tests still pass (no regression)

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly

## Key Design Decisions

1. **Daemon-side resolution**: Identity is resolved when the daemon accepts the socket connection, not in the MCP wrapper. The wrapper remains a transparent stdio proxy. This centralizes auth logic and prevents spoofing.

2. **os_username vs username**: The existing `PersonEntry.username` is a display name. The new `os_username` explicitly maps to the OS-level user account. They serve different purposes and may have different values.

3. **Public role for unknowns**: Unknown UIDs get `public` role rather than being rejected outright. This allows the system to gracefully handle connections from unmapped users (e.g., service accounts, containers) while enforcing least privilege.

4. **No wrapper changes**: The MCP wrapper does not need to extract or pass credentials. The daemon reads them directly from the accepted socket connection. This is simpler and more secure.
