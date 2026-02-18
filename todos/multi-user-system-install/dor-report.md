# DOR Report: multi-user-system-install

## Draft Assessment (not a formal gate verdict)

### Gate 1: Intent & Success — PASS

The input brain dump is exceptionally detailed. Problem statement, intended outcome, design decisions, and success criteria are all explicit and testable. Requirements have been formalized from the input.

### Gate 2: Scope & Size — FAIL

**This todo is too large for a single AI session.** The input itself acknowledges this: "This is a large architectural project, not a single session's work." The implementation plan proposes 6 dependent phases, each substantial enough to be its own todo.

**Remediation**: Split into sub-todos with dependency graph. The implementation plan provides the breakdown.

### Gate 3: Verification — PASS (per phase)

Each phase has clear verification criteria: unit tests for credential extraction, visibility filtering checks, migration validation, service lifecycle tests. Integration tests span phase boundaries.

### Gate 4: Approach Known — PARTIAL

- Unix socket peer credentials: well-known OS facility, Python `socket` module supports it. Minor research needed on macOS `LOCAL_PEERCRED` specifics.
- Config merging: standard pattern, Pydantic schema already exists.
- Service user creation: well-documented for both `launchd` and `systemd`.
- **Open questions** remain on socket location, cost allocation, and worktree coordination. These are explicitly deferred or scoped out.

### Gate 5: Research Complete — NEEDS WORK

- `SO_PEERCRED` (Linux) and `LOCAL_PEERCRED` (macOS) Python socket API: needs targeted research before Phase 1 build.
- `launchd` plist and `systemd` unit file conventions for Python services: needs research before Phase 5 build.
- No third-party library dependencies anticipated (pure stdlib + existing stack).

### Gate 6: Dependencies & Preconditions — PASS

- `doc-access-control` is delivered.
- Session identity model is stable.
- People/identity configuration exists.
- No external system dependencies beyond the OS.

### Gate 7: Integration Safety — PASS

Each phase can be merged incrementally. Single-user mode continues to work throughout. System-wide mode is opt-in. No destructive changes to existing functionality.

### Gate 8: Tooling Impact — NOT APPLICABLE

No tooling or scaffolding changes in first pass.

## Assumptions

1. The existing command queue serialization is sufficient to handle multi-user write contention on SQLite.
2. Python's `socket` module exposes peer credential retrieval on both macOS and Linux.
3. Daemon can detect single-user vs system-wide mode at startup and load paths accordingly.
4. Per-user config is purely additive (preferences only); it cannot override system-level settings.

## Open Questions

1. Socket file location in system mode: `/tmp/` vs `/var/run/teleclaude/`.
2. Should cost/token tracking be part of this project or a separate todo? (Recommendation: separate.)
3. What happens when the `teleclaude` service user doesn't exist yet? (Recommendation: installer script handles creation.)

## Recommendation

**Do not attempt to build this todo as-is.** Split into the 6 sub-todos defined in the implementation plan:

1. `multi-user-identity` — OS user identity resolution (foundation, no dependencies)
2. `multi-user-sessions` — Session ownership & visibility (depends on 1)
3. `multi-user-admin-audit` — Admin observability & audit logging (depends on 2)
4. `multi-user-config` — Config separation into system/secrets/personal (depends on 1)
5. `multi-user-service` — Service user & system-wide installation (depends on 4)
6. `multi-user-migration` — Migration tooling from single-user (depends on 5)

Each sub-todo should go through its own DOR draft → gate cycle before build.
