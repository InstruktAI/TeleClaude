# Input: ucap-ingress-provisioning-harmonization

## Source Context

- `todos/roadmap.yaml` defines this as Phase 5 of `unified-client-adapter-pipeline`:
  standardize ingress semantics and centralize channel/provisioning orchestration.
- Parent scope appears in `todos/unified-client-adapter-pipeline/{requirements,implementation-plan}.md`
  under:
  - unified ingress mapping
  - channel/provisioning consistency

## Problem Signal

- Input handling and provenance updates are split across adapter paths and command handling paths.
- Channel provisioning behavior is centralized in `AdapterClient.ensure_ui_channels()`, but this slug
  must validate and tighten that as the single orchestration boundary for UI adapters.
- The same behavioral contract must hold for Web/TUI/Telegram/Discord input and channel creation
  decisions without adapter-specific drift.

## Known Code Touchpoints

- Ingress mapping:
  - `teleclaude/core/command_mapper.py`
  - `teleclaude/core/command_handlers.py` (`process_message`, voice/input pathways)
  - `teleclaude/api_server.py` request-to-command mapping
- Provisioning orchestration:
  - `teleclaude/core/adapter_client.py` (`create_channel`, `ensure_ui_channels`, routing)
  - `teleclaude/adapters/telegram_adapter.py` (`ensure_channel`)
  - `teleclaude/adapters/discord_adapter.py` (`ensure_channel`)
  - `teleclaude/adapters/ui_adapter.py` command dispatch hooks

## Dependency

- Blocked by roadmap dependency: `ucap-canonical-contract`.

## Open Questions

1. Ingress scope boundary: interactive adapters only (Web/TUI/Telegram/Discord) vs including hook ingress.
2. Provisioning scope boundary: UI channel provisioning only vs also transport routing/provisioning behavior.
