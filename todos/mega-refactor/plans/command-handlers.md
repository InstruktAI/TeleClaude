# command_handlers.py

- Split handlers into domain modules: `handlers/sessions.py`, `handlers/agents.py`, `handlers/system.py`, `handlers/files.py`.
- Keep shared helpers in `handlers/common.py`.
- Export registry in `handlers/__init__.py`.
