# Input

## Objective

Stop concurrent overwrite collisions on dirty `main` while keeping agent workflow simple.

## Non-negotiables from requester

1. Work continues directly on `main`.
2. Locking must be transparent to agents (no extra cognitive steps).
3. Agent remains owner of commit (`git add`/`git commit`).
4. On lock contention:
   - emit heartbeat,
   - do not rapid-retry,
   - retry after 3 minutes.
5. If still blocked after retry, hard-stop and report blocker clearly.
6. Anything not alive cannot own locks.
7. No daemon-owned commit automation.
8. No default Git surgery choreography as control path.

## Design framing

This todo defines a standard lease/ownership model for file edits with deterministic
contention behavior and explicit lifecycle cleanup.
