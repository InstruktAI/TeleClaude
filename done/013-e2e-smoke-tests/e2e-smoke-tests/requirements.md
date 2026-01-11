# Requirements: End-to-End Smoke Tests

## Problem Statement

TeleClaude has a complex event-driven architecture spanning multiple components:
- DaemonCache (TTL, interest tracking, notifications)
- REST adapter (WebSocket server, cache integration)
- Redis adapter (cross-computer event push/receive)
- TUI client (WebSocket subscription, real-time updates)

Currently there's no single test that validates the entire data flow works correctly. Regressions can hide in the integration points between components.

## Goal

Create a comprehensive end-to-end smoke test suite that:
1. Validates the complete WebSocket → Cache → Redis → WebSocket data flow
2. Can run nightly or on-demand to catch integration regressions
3. Is read-only (no actual session creation, uses mocks/fixtures)
4. Runs fast enough for CI (<30 seconds)

## Success Criteria

### Must Have

1. **WebSocket subscription flow tested**
   - Client connects to `/ws` endpoint
   - Client subscribes to "sessions"
   - Cache interest correctly tracked
   - Disconnect clears interest

2. **Cache notification chain tested**
   - Cache update triggers subscriber callbacks
   - REST adapter receives notification
   - WebSocket clients receive pushed events

3. **Cross-computer event simulation**
   - Simulated Redis stream event received
   - Cache updated from event
   - WebSocket notification sent

4. **TTL/staleness verified**
   - Stale data filtered from responses
   - Fresh data returned correctly

5. **All tests pass in CI**
   - `make test-e2e` includes these tests
   - Tests run in <30 seconds total

### Should Have

6. **Multiple client isolation**
   - Multiple WebSocket clients receive broadcasts
   - Subscription filtering works (only get subscribed events)

7. **Error resilience tested**
   - Dead WebSocket client removed on send failure
   - Redis connection failure handled gracefully

8. **Heartbeat interest advertising**
   - Interest included in heartbeat when subscribed
   - Interest cleared when all clients disconnect

### Nice to Have

9. **Performance baseline**
   - Measure event propagation latency
   - Alert if latency exceeds threshold

10. **Documentation**
    - Test scenarios documented in test file docstrings
    - README for running smoke tests manually

## Non-Goals

- No actual multi-computer testing (that requires infrastructure)
- No load testing (separate concern)
- No UI testing (TUI is curses-based, hard to test)

## Technical Constraints

1. **Read-only tests** - Don't create real sessions or modify state
2. **Mock Redis** - Use mocked Redis client, not real Redis
3. **In-process** - All components run in test process
4. **Deterministic** - No timing-dependent assertions (use explicit waits)

## Test File Location

```
tests/integration/test_e2e_smoke.py
```

## Verification

```bash
# Run smoke tests specifically
pytest tests/integration/test_e2e_smoke.py -v

# Run as part of full suite
make test-e2e
```

## Usage Patterns

### Nightly CI
```yaml
# .github/workflows/nightly.yml
- name: Run smoke tests
  run: pytest tests/integration/test_e2e_smoke.py -v --tb=short
```

### Pre-deploy check
```bash
# Before deploying to production
make test-e2e && teleclaude__deploy()
```

### Local development
```bash
# After making changes to event flow
pytest tests/integration/test_e2e_smoke.py -v
```
