# Parallelization Map

All items can run in parallel because they only touch their own module trees. The only shared change is import wiring inside the file being refactored.

Independent work units:
- `daemon.py`
- `adapters/redis_adapter.py`
- `core/command_handlers.py`
- `core/next_machine.py`
- `core/adapter_client.py`
- `adapters/rest_adapter.py`
- `core/terminal_bridge.py`
- `cli/tui/views/preparation.py`
- `core/db.py`
- `mcp/handlers.py`
- `cli/tui/views/sessions.py`

Notes:
- If any refactor introduces new shared helpers, keep them within the same module subtree to avoid cross‑unit coupling.
- Avoid renaming external symbols unless the refactor for that file updates its own import sites.
