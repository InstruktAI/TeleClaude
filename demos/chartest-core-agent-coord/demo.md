# Demo: chartest-core-agent-coord

## Validation

Run the new characterization tests to confirm they pass against the current codebase.

```bash
python -m pytest tests/unit/core/agent_coordinator/ -v --tb=short -q 2>&1 | tail -20
```

```bash
python -m pytest tests/unit/core/agent_coordinator/ --co -q 2>&1 | grep "test session" | head -5
```

## Guided Presentation

The delivery adds 4 characterization test files covering the agent coordinator subsystem:

1. `test__helpers.py` — pins pure helper functions: checkpoint detection, codex synthetic event
   classification, identity resolution candidates, suppression state dataclass, and UTC normalization.

2. `test__incremental.py` — pins the suppression-state tracking methods on `_IncrementalOutputMixin`:
   signature hashing, noop state lifecycle, tool_use skip tracking, and `trigger_incremental_output`
   guard conditions.

3. `test__fanout.py` — pins the async extraction, TTS, notification, and snapshot guard paths on
   `_FanoutMixin`: summarization failures, Codex extraction skips, headless snapshot guards, and
   linked fanout with empty links.

4. `test__coordinator.py` — pins `AgentCoordinator` construction, event dispatch routing, activity
   and status event emission, and the tool_done/session_end handlers.

All tests pass immediately — this is expected for characterization. Each test is designed to catch
a real mutation in the production code (verified during authoring).
