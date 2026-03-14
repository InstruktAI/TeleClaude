# Implementation Plan: chartest-core-domain

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [ ] Characterize `teleclaude/core/activity_contract.py` → `tests/unit/core/test_activity_contract.py`
- [ ] Characterize `teleclaude/core/agent_parsers.py` → `tests/unit/core/test_agent_parsers.py`
- [ ] Characterize `teleclaude/core/agents.py` → `tests/unit/core/test_agents.py`
- [ ] Characterize `teleclaude/core/cache.py` → `tests/unit/core/test_cache.py`
- [ ] Characterize `teleclaude/core/checkpoint_dispatch.py` → `tests/unit/core/test_checkpoint_dispatch.py`
- [ ] Characterize `teleclaude/core/codex_prompt_normalization.py` → `tests/unit/core/test_codex_prompt_normalization.py`
- [ ] Characterize `teleclaude/core/codex_prompt_submit.py` → `tests/unit/core/test_codex_prompt_submit.py`
- [ ] Characterize `teleclaude/core/codex_transcript.py` → `tests/unit/core/test_codex_transcript.py`
- [ ] Characterize `teleclaude/core/command_mapper.py` → `tests/unit/core/test_command_mapper.py`
- [ ] Characterize `teleclaude/core/command_registry.py` → `tests/unit/core/test_command_registry.py`
- [ ] Characterize `teleclaude/core/command_service.py` → `tests/unit/core/test_command_service.py`
- [ ] Characterize `teleclaude/core/dates.py` → `tests/unit/core/test_dates.py`
- [ ] Characterize `teleclaude/core/db_models.py` → `tests/unit/core/test_db_models.py`
- [ ] Characterize `teleclaude/core/error_feedback.py` → `tests/unit/core/test_error_feedback.py`
- [ ] Characterize `teleclaude/core/event_bus.py` → `tests/unit/core/test_event_bus.py`
- [ ] Characterize `teleclaude/core/event_guard.py` → `tests/unit/core/test_event_guard.py`
- [ ] Characterize `teleclaude/core/events.py` → `tests/unit/core/test_events.py`
- [ ] Characterize `teleclaude/core/feature_flags.py` → `tests/unit/core/test_feature_flags.py`
- [ ] Characterize `teleclaude/core/feedback.py` → `tests/unit/core/test_feedback.py`
- [ ] Characterize `teleclaude/core/file_handler.py` → `tests/unit/core/test_file_handler.py`
- [ ] Characterize `teleclaude/core/identity.py` → `tests/unit/core/test_identity.py`
- [ ] Characterize `teleclaude/core/inbound_errors.py` → `tests/unit/core/test_inbound_errors.py`
- [ ] Characterize `teleclaude/core/inbound_queue.py` → `tests/unit/core/test_inbound_queue.py`
- [ ] Characterize `teleclaude/core/metadata.py` → `tests/unit/core/test_metadata.py`
- [ ] Characterize `teleclaude/core/origins.py` → `tests/unit/core/test_origins.py`
- [ ] Characterize `teleclaude/core/output_poller.py` → `tests/unit/core/test_output_poller.py`
- [ ] Characterize `teleclaude/core/parsers.py` → `tests/unit/core/test_parsers.py`
- [ ] Characterize `teleclaude/core/polling_coordinator.py` → `tests/unit/core/test_polling_coordinator.py`
- [ ] Characterize `teleclaude/core/redis_utils.py` → `tests/unit/core/test_redis_utils.py`
- [ ] Characterize `teleclaude/core/roadmap.py` → `tests/unit/core/test_roadmap.py`
- [ ] Characterize `teleclaude/core/session_launcher.py` → `tests/unit/core/test_session_launcher.py`
- [ ] Characterize `teleclaude/core/session_listeners.py` → `tests/unit/core/test_session_listeners.py`
- [ ] Characterize `teleclaude/core/session_utils.py` → `tests/unit/core/test_session_utils.py`
- [ ] Characterize `teleclaude/core/status_contract.py` → `tests/unit/core/test_status_contract.py`
- [ ] Characterize `teleclaude/core/summarizer.py` → `tests/unit/core/test_summarizer.py`
- [ ] Characterize `teleclaude/core/system_stats.py` → `tests/unit/core/test_system_stats.py`
- [ ] Characterize `teleclaude/core/task_registry.py` → `tests/unit/core/test_task_registry.py`
- [ ] Characterize `teleclaude/core/tmux_delivery.py` → `tests/unit/core/test_tmux_delivery.py`
- [ ] Characterize `teleclaude/core/tmux_io.py` → `tests/unit/core/test_tmux_io.py`
- [ ] Characterize `teleclaude/core/todo_watcher.py` → `tests/unit/core/test_todo_watcher.py`
- [ ] Characterize `teleclaude/core/tool_access.py` → `tests/unit/core/test_tool_access.py`
- [ ] Characterize `teleclaude/core/tool_activity.py` → `tests/unit/core/test_tool_activity.py`
- [ ] Characterize `teleclaude/core/voice_assignment.py` → `tests/unit/core/test_voice_assignment.py`
- [ ] Characterize `teleclaude/core/voice_message_handler.py` → `tests/unit/core/test_voice_message_handler.py`
