# DOR Report: multi-user-identity

## Draft Assessment

### Gate 1: Intent & Success — PASS

Problem statement is clear: MCP socket has no caller authentication. Success criteria are concrete and testable (UID extraction, person resolution, unknown fallback, platform support).

### Gate 2: Scope & Size — PASS

Atomic and focused: one new module (`socket_auth.py`), one config field addition, integration into socket accept path. Fits a single AI session comfortably.

### Gate 3: Verification — PASS

Unit tests for each resolution step. Integration test for full pipeline. `make test` and `make lint` as quality gates.

### Gate 4: Approach Known — PARTIAL

- `SO_PEERCRED` on Linux: well-documented, Python `socket.SO_PEERCRED` constant exists.
- `LOCAL_PEERCRED` on macOS: less documented in Python context. The constant may not be in the `socket` module — may need raw integer values. `struct xucred` format needs verification.
- `pwd.getpwuid()`: standard Python stdlib, no issues.
- Person lookup: simple list scan, established pattern.

### Gate 5: Research Complete — NEEDS WORK

- **macOS LOCAL_PEERCRED**: Exact Python API for extracting peer credentials on macOS Unix sockets needs targeted research. Key questions:
  - Is `LOCAL_PEERCRED` available as a socket constant in Python?
  - What is the `struct xucred` layout on modern macOS?
  - Does `socket.getsockopt()` work with these on macOS?
- **Linux SO_PEERCRED**: Better documented, but verify `struct ucred` layout and Python struct format string.
- No third-party libraries needed — pure stdlib.

### Gate 6: Dependencies & Preconditions — PASS

No dependencies on other phases. PersonEntry config schema is stable. Socket handling is in the daemon codebase.

### Gate 7: Integration Safety — PASS

Additive change. Existing identity flows (Telegram, Discord) are completely unaffected. The new `os_username` field is optional — existing configs without it continue to work. Unknown UIDs get public role rather than being rejected.

### Gate 8: Tooling Impact — N/A

No tooling or scaffolding changes.

## Assumptions

1. Python's `socket.getsockopt()` can extract peer credentials on both macOS and Linux.
2. `pwd.getpwuid()` is reliable for UID → username mapping on both platforms.
3. The MCP backend accepts connections via a standard Unix socket that exposes peer credentials.
4. Identity resolution is fast enough to happen synchronously on socket accept (it's a config lookup, not a DB query).

## Open Questions

1. Exact `LOCAL_PEERCRED` constant value and `struct xucred` layout on macOS — needs research.
2. Should identity resolution happen per-connection or per-request? Per-connection is simpler and correct (UID doesn't change during a connection).

## Score: 6/10

Research gate (Gate 5) is the primary blocker. Once macOS socket credential API is verified, this moves to 8+.
