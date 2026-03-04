# Demo: agent-session-auth

## Validation

```bash
# 1. Verify token is issued at session spawn
# Start a session and check the DB for a token record
telec sessions start --project /Users/Morriz/Workspace/InstruktAI/TeleClaude --agent claude --mode fast --message "echo \$TELEC_SESSION_TOKEN"
```

```bash
# 2. Verify token is in tmux env
# Inside the spawned session, the token env var should be set
tmux show-environment -t tc_<session_prefix> TELEC_SESSION_TOKEN
```

```bash
# 3. Verify telec auth whoami returns principal inside agent session
# From within the agent session:
telec auth whoami
# Expected: "Principal: human:maurice@instrukt.ai" (if human-delegated)
# or "Principal: system:<session_prefix>" (if system/job)
```

```bash
# 4. Verify CLI calls succeed with token auth
# From within the agent session:
telec sessions list
# Should succeed (token validated against ledger)
```

```bash
# 5. Verify token revocation on session close
# Close the session and try the token again
telec sessions end <session_id>
# Then manually test: the token should be revoked in the DB
```

```bash
# 6. Verify revoked token is rejected
# Using the revoked token should fail with 401
curl -s --unix-socket /tmp/teleclaude-api.sock \
  -H "X-Session-Token: <revoked_token>" \
  "http://localhost/sessions"
# Expected: 401 Unauthorized
```

## Guided Presentation

### Step 1: Token Issuance

Start a new agent session and observe the bootstrap flow.

**What to do:** Run `telec sessions start --project <path> --agent claude --mode fast --message "printenv TELEC_SESSION_TOKEN"`.

**What to observe:** The session starts normally. In the agent output, `TELEC_SESSION_TOKEN` is printed — a UUID that was issued by the daemon at bootstrap time.

**Why it matters:** This proves the daemon generates and injects a credential at spawn time, following the same env var injection path as voice configuration.

### Step 2: Principal Identity

Check who the session thinks it is.

**What to do:** From within the agent session, run `telec auth whoami`.

**What to observe:** The output shows the principal — either `human:maurice@instrukt.ai` (because the session was spawned by a logged-in human) or `system:<prefix>` for automated sessions.

**Why it matters:** Two principal types are supported. The daemon determines the type from session state at issuance time.

### Step 3: Authenticated CLI Call

Verify the token enables normal operations.

**What to do:** From within the agent session, run `telec sessions list`.

**What to observe:** The session list is returned normally. The CLI sent the token in the `X-Session-Token` header, and the daemon validated it against the ledger.

**Why it matters:** Agent sessions can make authenticated API calls using their issued credential, without relying solely on session ID + tmux cross-check.

### Step 4: Revocation on Close

Close the session and verify the token is dead.

**What to do:** Run `telec sessions end <session_id>`.

**What to observe:** The session closes. If you inspect the DB, the token's `revoked_at` field is now set. Any attempt to use that token returns 401.

**Why it matters:** Token lifetime is tied to session lifetime. When a session ends, its credential dies with it. No stale credentials persist.
