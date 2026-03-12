# Requirements: agent-session-auth

## Goal

Every agent session must have a verifiable identity before it can act. No agent runs unauthorized. Two principal types: human-delegated and system/job. Principals carry a role that gates what commands the session may execute. [inferred from roadmap description — input.md contains no human brain dump]

## Scope

### In scope:

- Token issuance at session spawn (daemon creates token, records in ledger)
- Two principal types: `human:<email>` (human-started) and `system:<job-id>` (event/job-started)
- Principals carry a role: the principal's role is used for authorization when no human_role is present
- Ledger table in `teleclaude.db` [inferred]: sufficient fields to record the principal, validate token authenticity, enforce TTL expiry, and support revocation
- `telec` CLI reads token from env var (`TELEC_SESSION_TOKEN`, injected into agent tmux session at spawn) and presents it to daemon via `X-Session-Token` header
- Daemon validates token against ledger before granting role
- Token revoked on session close (daemon-controlled, not dependent on agent runtime)
- `telec sessions send` and all agent-initiated CLI calls work once credentialed
- Clearance bypass: `is_command_allowed()` accepts a principal as a valid alternative to human_role — sessions with a principal are not blocked by the `human_role is None` denial
- Child session inheritance: when an agent session spawns a child (via `telec sessions run`), the principal propagates to the child session — same pattern as existing human_email/human_role inheritance

### Out of scope:

- Changing the `tc_tui` / `TELEC_TUI_SESSION` bridge (untouched — human TTY auth stays as-is)
- Cross-computer token federation (local only for now)
- Token rotation mid-session

## Success Criteria

- [ ] Agent sessions have a token in their tmux env (`TELEC_SESSION_TOKEN`) at spawn time
- [ ] `telec auth whoami` returns the principal inside an agent session
- [ ] `telec sessions send` succeeds from an agent session with the correct role
- [ ] Ledger records every issued token with expiry
- [ ] Session close revokes the token; subsequent CLI calls fail
- [ ] System/job sessions get a system principal, not a human email
- [ ] `is_command_allowed()` permits calls when a valid principal is present, even without human_role
- [ ] Child sessions inherit the parent's principal when no human identity is available

## Constraints

- `tc_tui` trust boundary must not be modified
- Tokens must be temporary (TTL = session lifetime, 24h safety cap)
- Tokens must be checked against the ledger, not just decoded locally
- Principals must carry a role to prevent abuse — a principal without a role cannot authorize commands
- New DB table requires a migration following the existing migration sequence [inferred from DoD — schema changes must be versioned]

## Risks

- Token in env var is readable by any process in the tmux session — acceptable for now, same as current `TELEC_AUTH_EMAIL` pattern in TUI
- System principal identity requires a stable, traceable naming scheme — format is a builder decision [inferred]
