# Demo: bidirectional-agent-links

## Validation

<!-- Bash code blocks that prove the feature works. -->
<!-- Blocks are validated by `telec todo demo validate bidirectional-agent-links` during build. -->
<!-- Execution (`telec todo demo run bidirectional-agent-links`) happens on main after merge. -->

```bash
# 1) Baseline health + demo artifact validation
make status
telec todo demo validate bidirectional-agent-links
```

Expected:

- Daemon reports healthy status.
- Demo artifact is structurally valid.

```bash
# 2) Core link behavior and regression checks
pytest tests/unit/test_session_listeners.py tests/unit/test_agent_coordinator.py tests/unit/test_session_cleanup.py -q
pytest tests/unit/test_bidirectional_links.py -q
```

Expected:

- Direct link handshake/create-reuse logic passes.
- Sender-excluded fan-out and checkpoint/empty-output filtering pass.
- Non-direct worker notification behavior remains unchanged.
- Session-end cleanup removes links and prevents orphan injection.

```bash
# 3) Optional runtime observability spot-check after a direct-link exchange
instrukt-ai-logs teleclaude --since 15m --grep "direct|link|agent_stop|cleanup"
```

## Guided Presentation

1. Run health and artifact validation first to confirm a clean baseline.
2. Run focused unit tests for listener behavior, stop-output routing, and cleanup guarantees.
3. Run the dedicated direct-link test suite to confirm 2-member and 3-member fan-out semantics plus `close_link` severing behavior.
4. For cross-computer confidence, execute a direct exchange between sessions on different computers and use the log grep to confirm forwarded stop output and cleanup events.
