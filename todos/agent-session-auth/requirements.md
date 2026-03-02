# Requirements: agent-session-auth

## Goal

Every agent session must have a verifiable identity before it can act. No agent runs unauthorized. Two principal types: human-delegated and system/job.

## Scope

### In scope:
- Token issuance at session spawn (daemon creates short-lived token, records in ledger)
- Two principal types: `human:<email>` (human-started) and `system:<job-id>` (event/job-started)
- Ledger table in DB: session_id, principal, token, issued_at, expires_at, revoked
- `telec` CLI reads token from env (injected into agent tmux session at spawn) and presents it to daemon
- Daemon validates token against ledger before granting role
- Token revoked on session close
- `telec sessions send` and all agent-initiated CLI calls work once credentialed

### Out of scope:
- Changing the `tc_tui` / `TELEC_TUI_SESSION` bridge (untouched — human TTY auth stays as-is)
- Cross-computer token federation (local only for now)
- Token rotation mid-session

## Success Criteria

- [ ] Agent sessions have a token in their tmux env at spawn time
- [ ] `telec auth whoami` returns the principal inside an agent session
- [ ] `telec sessions send` succeeds from an agent session with the correct role
- [ ] Ledger records every issued token with expiry
- [ ] Session close revokes the token; subsequent CLI calls fail
- [ ] System/job sessions get a system principal, not a human email

## Constraints

- `tc_tui` trust boundary must not be modified
- Tokens must be temporary (TTL = session lifetime)
- Tokens must be checked against the ledger, not just decoded locally

## Risks

- Token in env var is readable by any process in the tmux session — acceptable for now, same as current `TELEC_AUTH_EMAIL` pattern in TUI
- System principal identity needs a stable naming scheme before implementation
