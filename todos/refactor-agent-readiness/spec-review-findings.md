# Spec Review Findings: refactor-agent-readiness

Verdict: `needs_work`

1. Critical: SC-1 is still not pinned at the detector boundary. [tests/unit/core/test_agent_readiness.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/refactor-agent-readiness/tests/unit/core/test_agent_readiness.py#L19) through [tests/unit/core/test_agent_readiness.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/refactor-agent-readiness/tests/unit/core/test_agent_readiness.py#L92) only exercise `agent_name="claude"`, while [tests/unit/core/test_agents.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/refactor-agent-readiness/tests/unit/core/test_agents.py#L120) and [tests/unit/core/test_agents.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/refactor-agent-readiness/tests/unit/core/test_agents.py#L128) only prove that `AgentName.prompt_marker` exists. Nothing asserts that `wait_for_agent_ready()` resolves its prompt marker from that metadata for the requested agent. A detector with its own hardcoded marker table, or one that always checks Claude's marker, would still satisfy the suite.

2. Important: The detector's no-side-effects contract is untested. [tests/unit/core/test_agent_readiness.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/refactor-agent-readiness/tests/unit/core/test_agent_readiness.py#L19) only fences `tmux_bridge.capture_pane` and asserts the returned `(ready, tail)` pair. The requirements keep event emission, session cleanup, and user notification in daemon-session orchestration, but no spec fails if `wait_for_agent_ready()` emits readiness events, terminates the session, or notifies the client itself. That leaves the boundary-purity invariant unenforced.

3. Important: SC-5's user-notification branch is only smoke-tested. [tests/unit/test_daemon_session.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/refactor-agent-readiness/tests/unit/test_daemon_session.py#L429) through [tests/unit/test_daemon_session.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/refactor-agent-readiness/tests/unit/test_daemon_session.py#L433) only assert that `client.send_message()` was called with the same session. A wrong implementation that sends an unrelated status or success message to that session would still pass. The spec should pin the stable failure-notification contract at that boundary, not just "some message was sent."

Verification:

- `pytest tests/unit/core/test_agent_readiness.py tests/unit/core/test_agents.py tests/unit/core/test_events.py tests/unit/test_daemon_session.py -q` → `46 passed, 12 xfailed`
