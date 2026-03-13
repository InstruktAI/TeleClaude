# Demo: rlf-core-infra

## Validation

### Package structure: tmux_bridge

```bash
# Verify tmux_bridge is now a package with focused submodules
ls teleclaude/core/tmux_bridge/
python -c "from teleclaude.core.tmux_bridge import send_keys, capture_pane, ensure_tmux_session; print('tmux_bridge imports OK')"
```

### Package structure: agent_coordinator

```bash
# Verify agent_coordinator is now a package with focused submodules
ls teleclaude/core/agent_coordinator/
python -c "from teleclaude.core.agent_coordinator import AgentCoordinator, SESSION_START_MESSAGES; print('agent_coordinator imports OK')"
```

### Package structure: adapter_client

```bash
# Verify adapter_client is now a package with focused submodules
ls teleclaude/core/adapter_client/
python -c "from teleclaude.core.adapter_client import AdapterClient; print('adapter_client imports OK')"
```

### Module size compliance

```bash
# No submodule exceeds 800 lines (hard ceiling)
python -c "
import pathlib
hard_ceiling = 800
violations = []
for pkg in ['teleclaude/core/tmux_bridge', 'teleclaude/core/agent_coordinator', 'teleclaude/core/adapter_client']:
    for f in pathlib.Path(pkg).glob('*.py'):
        lines = len(f.read_text().splitlines())
        if lines > hard_ceiling:
            violations.append(f'{f}: {lines} lines')
if violations:
    print('VIOLATIONS:', violations)
    exit(1)
else:
    print(f'All submodules within {hard_ceiling}-line ceiling: OK')
"
```

### Test suite

```bash
# Confirm tests still pass for all three packages
python -m pytest tests/ -x -q --no-header 2>&1 | tail -5
```

## Guided Presentation

Three large infrastructure modules were decomposed into focused packages:

1. `tmux_bridge.py` (1,402 lines) → `tmux_bridge/` package: `_subprocess.py`, `_pane.py`, `_session.py`, `_keys.py`
2. `agent_coordinator.py` (1,628 lines) → `agent_coordinator/` package: `_helpers.py`, `_incremental.py`, `_fanout.py`, `_coordinator.py`
3. `adapter_client.py` (1,161 lines) → `adapter_client/` package: `_channels.py`, `_output.py`, `_remote.py`, `_client.py`

All public APIs are preserved via `__init__.py` re-exports — zero callers required changes.
