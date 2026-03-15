# Demo: chartest-core-cmd-handlers

## Validation

```bash
. .venv/bin/activate && pytest tests/unit/core/command_handlers -v
```

```bash
rg -n 'Characterize `teleclaude/core/command_handlers/' todos/chartest-core-cmd-handlers/implementation-plan.md
```

## Guided Presentation

Run the command-handler unit test package and show that each of the five source files in scope now has a matching characterization test file under `tests/unit/core/command_handlers/`.

Point to the implementation plan and show that all five handler tasks are checked off:

- `_agent.py`
- `_keys.py`
- `_message.py`
- `_session.py`
- `_utils.py`

Explain that these tests pin current public-boundary behavior for session adoption, agent command handling, inbound delivery, transcript retrieval, and decorator-based session injection without changing production code.
