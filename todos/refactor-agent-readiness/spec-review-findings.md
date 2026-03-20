# Spec Review Findings: refactor-agent-readiness

Verdict: `needs_work`

1. Critical: SC-1 and the detector contract are not pinned at the detector boundary. [tests/unit/core/test_agent_readiness.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/refactor-agent-readiness/tests/unit/core/test_agent_readiness.py#L19) only exercises `agent_name="claude"` and checks for Claude's marker in the returned tail. [tests/unit/core/test_agents.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/refactor-agent-readiness/tests/unit/core/test_agents.py#L128) proves `AgentName.prompt_marker` exists, but nothing asserts that `wait_for_agent_ready()` resolves its marker from that metadata for each agent. A detector that hardcodes a second marker map, or always checks Claude's marker, would still satisfy this suite.

2. Critical: SC-3 is covered with implementation leakage instead of observable behavior. [tests/unit/test_daemon_session.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/refactor-agent-readiness/tests/unit/test_daemon_session.py#L422) requires three private helper names to disappear from `_DaemonSessionMixin`. That can pass while `_handle_agent_then_message()` still performs direct pane polling through renamed or inlined logic, and it can fail on a harmless internal shim that is no longer used. The spec should pin the daemon boundary behavior instead: once readiness is delegated to the detector, the message-injection path itself does not call pane-capture or polling primitives.

3. Important: the timeout notification spec is a prose-lock test. [tests/unit/test_daemon_session.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/refactor-agent-readiness/tests/unit/test_daemon_session.py#L419) asserts that the user-facing message contains `"timeout"` or `"failed"`. The testing policy forbids string assertions on human-facing output. This will fail on harmless wording changes while the timeout behavior remains correct. The spec should assert the structured failure contract at the notifier boundary instead of its rendered prose.

Verification:
- `pytest tests/unit/core/test_agent_readiness.py tests/unit/core/test_agents.py tests/unit/core/test_events.py tests/unit/test_daemon_session.py -q` → `46 passed, 14 xfailed`
