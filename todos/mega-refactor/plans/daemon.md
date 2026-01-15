# daemon.py

- Extract long‑running loops (outbox workers, monitors) into `teleclaude/core/` submodules with start/stop helpers.
- Extract agent auto‑start detection to `teleclaude/core/agent_startup.py`.
- Consolidate event wiring in `teleclaude/core/daemon_wiring.py`.
- Move daemon constants to `teleclaude/daemon_config.py`.
- Keep `daemon.py` as orchestration + lifecycle integration only.
