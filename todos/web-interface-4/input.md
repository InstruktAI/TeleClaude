# Web Interface — Phase 4: Session Management & Role-Based Access

## Context

This is phase 4 of the web-interface breakdown. Depends on phase 3
(chat interface). See the parent todo's `input.md` for full context.

## Intended Outcome

Session management sidebar, session switching, new session creation, and
role-based visibility routing.

## What to Build

1. **Session list sidebar** — active sessions with title, agent icon, last activity, status.
2. **Session switching** — click to change which session the SSE stream follows.
3. **New session creation** — project/agent picker, title input.
4. **Session actions** — end session.
5. **Visibility routing** — private by default, admin sees all, shared sessions for members.
6. **Admin dashboard** — computers with status, projects, active session counts.

## Verification

- Session list shows real-time status updates.
- Switching sessions reconnects SSE stream correctly.
- New session creation works from browser.
- Non-owner blocked from viewing private sessions (403).
- Admin sees all sessions.
