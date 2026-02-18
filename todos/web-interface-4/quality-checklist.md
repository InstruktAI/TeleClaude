# Quality Checklist: web-interface-4

## Build Gates (Builder)

- [ ] All implementation-plan tasks checked off
- [ ] Daemon visibility filtering applied to GET /sessions
- [ ] Access check helper on session-scoped endpoints
- [ ] Visibility field on session model
- [ ] Sidebar layout with session list
- [ ] Session switching works with existing key-based pattern
- [ ] Session header component with end session action
- [ ] New session creation dialog with full flow
- [ ] WebSocket real-time session list updates
- [ ] Admin dashboard with computer/project/session cards
- [ ] Dashboard route protected for admin-only
- [ ] Tests pass: `make test`
- [ ] Lint passes: `make lint`
- [ ] Clean working tree (build-scope changes committed)

## Review Gates (Reviewer)

- [ ] Code follows existing patterns and conventions
- [ ] No security vulnerabilities introduced
- [ ] Error handling is consistent with existing proxy routes
- [ ] TypeScript types match Python API models
- [ ] No breaking changes to existing functionality

## Finalize Gates (Finalizer)

- [ ] Branch ready for merge
- [ ] Delivery log updated
