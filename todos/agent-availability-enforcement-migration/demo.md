# Demo: agent-availability-enforcement-migration

## Validation

```bash
# Targeted regression surfaces for availability enforcement
pytest -q \
  tests/unit/test_api_server.py \
  tests/unit/test_command_handlers.py \
  tests/unit/test_command_mapper.py \
  tests/unit/test_daemon.py \
  tests/unit/test_discord_adapter.py \
  tests/unit/test_telegram_adapter.py \
  tests/unit/test_whatsapp_adapter.py \
  tests/unit/test_cron_runner_job_contract.py \
  tests/unit/cli/test_tool_commands.py
```

```bash
# Mark agent unavailable for runtime validation
telec agents status claude --status unavailable --reason dor-demo --until 2026-02-26T19:00:00Z
```

```bash
# Explicit selection must fail closed
telec sessions run \
  --command /next-build \
  --args agent-availability-enforcement-migration \
  --project /Users/Morriz/Workspace/InstruktAI/TeleClaude \
  --agent claude
```

```bash
# If all agents are unavailable, implicit/default selection must fail closed too
telec agents status gemini --status unavailable --reason dor-demo --until 2026-02-26T19:00:00Z
telec agents status codex --status unavailable --reason dor-demo --until 2026-02-26T19:00:00Z
telec sessions run \
  --command /next-build \
  --args agent-availability-enforcement-migration \
  --project /Users/Morriz/Workspace/InstruktAI/TeleClaude
```

```bash
# Confirm rejection observability
instrukt-ai-logs teleclaude --since 15m --grep "agent routing|availability|rejected"
```

```bash
# Cleanup availability flags
telec agents status claude --clear
telec agents status gemini --clear
telec agents status codex --clear
```

## Guided Presentation

Medium: CLI + daemon logs.

1. Run targeted tests to show all migrated entry points enforce routing policy.
2. Mark `claude` unavailable and show explicit `--agent claude` launch is rejected.
3. Mark all agents unavailable and show implicit/default launch is rejected.
4. Show daemon log lines include source context and rejection reason.
5. Clear temporary availability status to restore baseline runtime behavior.
