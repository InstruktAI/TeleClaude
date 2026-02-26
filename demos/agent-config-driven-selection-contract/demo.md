# Demo: agent-config-driven-selection-contract

## Validation

```bash
# Validate demo artifact structure first
telec todo demo validate agent-config-driven-selection-contract
```

```bash
# Config contract + fail-closed behavior
uv run pytest -q \
  tests/unit/test_agent_config_loading.py \
  tests/unit/test_config.py \
  tests/unit/test_config_schema.py
```

```bash
# Selection/guidance policy behavior
uv run pytest -q \
  tests/unit/test_agent_guidance.py \
  tests/unit/test_agent_cli.py \
  tests/unit/test_agents.py
```

```bash
# Dispatch/start surface enforcement (API + command handlers)
uv run pytest -q \
  tests/unit/test_command_handlers.py \
  tests/unit/test_api_server.py \
  tests/integration/test_command_e2e.py
```

```bash
# TUI selection behavior follows enabled-agent policy
uv run pytest -q \
  tests/unit/test_tui_modal.py \
  tests/unit/test_tui_agent_status.py
```

## Guided Presentation

1. Open `config.yml` and show the `agents:` section. Set one agent enabled and one disabled, then run the validation blocks above.  
   Observe disabled agents are rejected consistently and enabled agents remain selectable.
2. Show a failure case by removing `agents:` (or setting all `enabled: false`) in a temporary test config fixture used by tests.  
   Observe actionable error messages that point to `config.yml` keys.
3. Trigger selection/dispatch flows through API + command tests.  
   Observe deterministic rejection for disabled agents in session/command-handler paths.
4. Review guidance output assertions in `test_agent_guidance.py`.  
   Observe no blank per-agent lines and explicit blocking message when no selectable agents exist.
5. Show TUI behavior from modal/status tests.  
   Observe selectable agent set is policy-driven (enabled + available), not hardcoded.
