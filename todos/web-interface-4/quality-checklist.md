# Quality Checklist: web-interface-4

## Build Gates (Builder)

- [x] All implementation-plan tasks checked off
- [x] Daemon visibility filtering applied to GET /sessions
- [x] Access check helper on session-scoped endpoints
- [x] Visibility field on session model
- [x] Sidebar layout with session list
- [x] Session switching works with existing key-based pattern
- [x] Session header component with end session action
- [x] New session creation dialog with full flow
- [x] WebSocket real-time session list updates
- [x] Admin dashboard with computer/project/session cards
- [x] Dashboard route protected for admin-only
- [x] Tests pass: `make test` (39 pre-existing failures, 0 new — no test files changed on branch)
- [x] Lint passes: `make lint`
- [x] Clean working tree (build-scope changes committed)

## Review Gates (Reviewer)

- [ ] Code follows existing patterns and conventions
- [ ] No security vulnerabilities introduced
- [ ] Error handling is consistent with existing proxy routes
- [ ] TypeScript types match Python API models
- [ ] No breaking changes to existing functionality

## Finalize Gates (Finalizer)

- [ ] Branch ready for merge
- [ ] Delivery log updated
