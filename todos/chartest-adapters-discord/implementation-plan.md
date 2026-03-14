# Implementation Plan: chartest-adapters-discord

## Approach

For each source file, follow OBSERVE-ASSERT-VERIFY:

1. Read the source, identify public functions/methods/classes
2. Write tests asserting observed behavior at public boundaries
3. Verify each test would catch a deliberate mutation

Commit after completing each file's characterization tests.

## Tasks

- [ ] Characterize `teleclaude/adapters/base_adapter.py` → `tests/unit/adapters/test_base_adapter.py`
- [ ] Characterize `teleclaude/adapters/discord_adapter.py` → `tests/unit/adapters/test_discord_adapter.py`
- [ ] Characterize `teleclaude/adapters/discord/channel_ops.py` → `tests/unit/adapters/discord/test_channel_ops.py`
- [ ] Characterize `teleclaude/adapters/discord/gateway_handlers.py` → `tests/unit/adapters/discord/test_gateway_handlers.py`
- [ ] Characterize `teleclaude/adapters/discord/infra.py` → `tests/unit/adapters/discord/test_infra.py`
- [ ] Characterize `teleclaude/adapters/discord/input_handlers.py` → `tests/unit/adapters/discord/test_input_handlers.py`
- [ ] Characterize `teleclaude/adapters/discord/message_ops.py` → `tests/unit/adapters/discord/test_message_ops.py`
- [ ] Characterize `teleclaude/adapters/discord/provisioning.py` → `tests/unit/adapters/discord/test_provisioning.py`
- [ ] Characterize `teleclaude/adapters/discord/relay_ops.py` → `tests/unit/adapters/discord/test_relay_ops.py`
- [ ] Characterize `teleclaude/adapters/discord/session_launcher.py` → `tests/unit/adapters/discord/test_session_launcher.py`
- [ ] Characterize `teleclaude/adapters/discord/team_channels.py` → `tests/unit/adapters/discord/test_team_channels.py`
