# Demo: telegram-callback-payload-migration

## Validation

```bash
# Verify legacy callback payloads still parse
python -c "
from teleclaude.adapters.telegram.callback_handlers import LEGACY_ACTION_MAP
assert LEGACY_ACTION_MAP['csel'] == ('asel', 'claude')
assert LEGACY_ACTION_MAP['gsel'] == ('asel', 'gemini')
assert LEGACY_ACTION_MAP['cxsel'] == ('asel', 'codex')
assert LEGACY_ACTION_MAP['c'] == ('as', 'claude')
print('Legacy mapping: OK')
"
```

```bash
# Verify dynamic keyboard uses enabled agents
python -c "
from teleclaude.adapters.telegram.callback_handlers import CallbackAction
# New generic actions exist
assert hasattr(CallbackAction, 'AGENT_SELECT')
assert hasattr(CallbackAction, 'AGENT_START')
assert hasattr(CallbackAction, 'AGENT_RESUME_SELECT')
assert hasattr(CallbackAction, 'AGENT_RESUME_START')
# Old per-agent actions removed
assert not hasattr(CallbackAction, 'CLAUDE_SELECT')
assert not hasattr(CallbackAction, 'GEMINI_SELECT')
assert not hasattr(CallbackAction, 'CODEX_SELECT')
print('CallbackAction enum: OK')
"
```

```bash
# Run the test suite to confirm no regressions
make test -- tests/unit/test_telegram_menus.py -v
```

## Guided Presentation

1. **Show the CallbackAction enum.** Open `callback_handlers.py` and confirm the enum uses
   generic action types (`AGENT_SELECT`, `AGENT_START`, etc.) instead of per-agent values.
   This proves the hardcoded abbreviations are gone.

2. **Show the legacy fallback map.** In the same file, find `LEGACY_ACTION_MAP`. This dict
   maps every old callback action (`csel`, `gsel`, `cxsel`, `c`, `g`, `cx`, and resume
   variants) to the new canonical `(action, agent_name)` tuple. Buttons already in user
   chats will continue to work.

3. **Show the dynamic keyboard.** Open `telegram_adapter.py` and find `_build_heartbeat_keyboard`.
   Instead of hardcoded rows per agent, it loops over `get_enabled_agents()`. Disable an
   agent in config and the button disappears. Enable a new agent and the button appears.

4. **Show the tests.** Open `test_telegram_menus.py`. Tests cover: new format parsing,
   legacy format parsing, dynamic keyboard with full and partial agent sets, and graceful
   rejection of unknown agents.

5. **Run the tests** to confirm everything passes.
