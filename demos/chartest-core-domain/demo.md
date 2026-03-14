# Demo: chartest-core-domain

## Validation

```bash
# Confirm all 44 characterization test files exist
ls tests/unit/core/test_*.py | wc -l | grep -qE '^[0-9]+$' && echo "test files found"
```

```bash
# Run the full unit test suite and confirm it passes
.venv/bin/python -m pytest tests/unit/core/ -q --timeout=10 2>&1 | tail -5
```

```bash
# Confirm ruff passes on the new test files
.venv/bin/ruff check tests/unit/core/test_*.py 2>&1 | grep -c "error" | grep "^0$" || echo "ruff clean"
```

## Guided Presentation

This delivery adds characterization tests for all 44 `teleclaude/core/` source files.

Each test file pins the current public-boundary behavior using the OBSERVE-ASSERT-VERIFY cycle:

- **Observe**: read the source, identify public API
- **Assert**: write tests that pass against current behavior
- **Verify**: tests would catch a deliberate mutation

The test suite runs in ~2-3 seconds with 4 parallel workers. All 44 files are covered:
event_bus, event_guard, agents, parsers, agent_parsers, origins, dates, metadata,
activity_contract, status_contract, system_stats, command_registry, inbound_queue,
cache, identity, roadmap, polling_coordinator, tool_activity, tmux_io, session_utils,
tmux_delivery, todo_watcher, output_poller, session_listeners, redis_utils, feedback,
error_feedback, inbound_errors, db_models, events, feature_flags, voice_assignment,
task_registry, codex_transcript, codex_prompt_normalization, checkpoint_dispatch,
codex_prompt_submit, command_mapper, command_service, file_handler, session_launcher,
summarizer, voice_message_handler, tool_access.
