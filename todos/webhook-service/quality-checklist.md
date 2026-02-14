# Quality Checklist: webhook-service

## Build Gates (Builder)

- [x] All implementation-plan tasks checked `[x]`
- [x] Tests pass (`make test`)
- [x] Lint passes (`make lint`) — 0 errors, 0 warnings
- [x] No debug/temp code committed
- [x] JSON serialization round-trips verified for HookEvent and Contract
- [x] Property matching covers all modes: exact, multi-value, wildcard, required, optional
- [x] DB CRUD methods follow existing patterns (async session, SQLModel)
- [x] Daemon wiring initializes all subsystems and handles graceful shutdown
- [x] 32 unit tests covering models, matcher, registry, dispatcher, delivery, bridge, config

## Review Gates (Reviewer)

- [ ] Code follows existing codebase conventions
- [ ] No security vulnerabilities (HMAC signing, input validation)
- [ ] Error handling is appropriate
- [ ] No unnecessary abstractions or over-engineering
- [ ] DB migrations are safe (additive schema only)

## Finalize Gates (Finalizer)

- [ ] Branch merged cleanly
- [ ] Delivery logged
- [ ] Cleanup complete
