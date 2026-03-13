# Deferrals: rlf-services

## make lint still fails (pre-existing oversized files)

**Scope:** Out of scope for this task

**Reason:** The guardrails module-size check fails for 19 files that were already over the 1000-line
limit before this task branch was created. These are not regressions introduced by this task.

Pre-existing oversized files (unchanged by this task):
- teleclaude/resource_validation.py (1171 lines)
- teleclaude/transport/redis_transport.py (1893 lines)
- teleclaude/core/db.py (2599 lines)
- teleclaude/core/models.py (1112 lines)
- teleclaude/core/adapter_client.py (1161 lines)
- teleclaude/core/command_handlers.py (2031 lines)
- teleclaude/core/tmux_bridge.py (1402 lines)
- teleclaude/core/agent_coordinator.py (1628 lines)
- teleclaude/utils/transcript.py (2327 lines)
- teleclaude/cli/telec.py (4401 lines)
- teleclaude/cli/tool_commands.py (1458 lines)
- teleclaude/adapters/ui_adapter.py (1048 lines)
- teleclaude/adapters/discord_adapter.py (2951 lines)
- teleclaude/adapters/telegram_adapter.py (1368 lines)
- teleclaude/hooks/checkpoint.py (1214 lines)
- teleclaude/hooks/receiver.py (1068 lines)
- teleclaude/helpers/youtube_helper.py (1385 lines)
- teleclaude/core/next_machine/core.py (4952 lines)
- teleclaude/core/integration/state_machine.py (1204 lines)

**Primary deliverables verified:**
- teleclaude/api_server.py: 906 lines ✓ (was 3323, now under 1000)
- teleclaude/daemon.py: 859 lines ✓ (was 2718, now under 1000)

**Follow-up:** Each of these files should be decomposed in separate focused tasks.
