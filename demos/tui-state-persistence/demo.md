# Demo: tui-state-persistence

## Validation

```bash
# Verify state file exists and has namespaced format
python3 -c "
import json, sys
state = json.load(open('$HOME/.teleclaude/tui_state.json'))
for key in ('sessions', 'preparation', 'status_bar', 'app'):
    assert key in state, f'Missing namespace: {key}'
print('State file has correct namespaced format')
"
```

```bash
# Verify Persistable protocol exists
python3 -c "
from teleclaude.cli.tui.persistence import Persistable
print(f'Persistable protocol imported: {Persistable}')
"
```

```bash
# Verify StatusBar implements Persistable
python3 -c "
from teleclaude.cli.tui.persistence import Persistable
from teleclaude.cli.tui.widgets.status_bar import StatusBar
assert hasattr(StatusBar, 'get_persisted_state'), 'Missing get_persisted_state'
assert hasattr(StatusBar, 'load_persisted_state'), 'Missing load_persisted_state'
print('StatusBar implements Persistable interface')
"
```

```bash
# Verify backward compat migration
python3 -c "
import json, tempfile, os
from pathlib import Path

# Write old flat format
old = {'sticky_sessions': [{'session_id': 'abc'}], 'animation_mode': 'party', 'expanded_todos': ['foo']}
tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w')
json.dump(old, tmp)
tmp.close()

# Patch path and load
import teleclaude.cli.tui.state_store as ss
original_path = ss.TUI_STATE_PATH
ss.TUI_STATE_PATH = Path(tmp.name)
try:
    state = ss.load_state()
    assert 'sessions' in state, 'Migration failed: missing sessions namespace'
    assert 'status_bar' in state, 'Migration failed: missing status_bar namespace'
    print('Backward compat migration works')
finally:
    ss.TUI_STATE_PATH = original_path
    os.unlink(tmp.name)
"
```

## Guided Presentation

### Step 1: Todo metadata refresh

**Do:** Edit `todos/mcp-migration-telec-commands/state.yaml` — change `build` field value.
**Observe:** The TUI todo view updates within ~2 seconds. The build status column reflects the change without pressing `r`.
**Why:** Previously, only slug additions/removals triggered a view rebuild. Now metadata changes are detected via fingerprinting.

### Step 2: Pane theming persistence

**Do:** Cycle pane theming mode by clicking the icon in the status bar (or pressing the shortcut). Note the current mode.
**Do:** Send SIGUSR2 to reload: `pkill -SIGUSR2 -f -- "-m teleclaude.cli.telec$"`
**Observe:** After reload, the pane theming mode is exactly as you left it.
**Why:** Pane theming is now persisted in `tui_state.json` via the Persistable protocol on StatusBar, instead of being routed through the daemon API.

### Step 3: Active tab persistence

**Do:** Switch to the Preparation tab.
**Do:** SIGUSR2 reload.
**Observe:** TUI comes back on the Preparation tab, not Sessions.
**Why:** Active tab is now persisted as app-level state.

### Step 4: State file inspection

**Do:** `cat ~/.teleclaude/tui_state.json | python3 -m json.tool`
**Observe:** Clean namespaced structure with `sessions`, `preparation`, `status_bar`, `app` keys.
**Why:** Generalized format replaces the old flat structure. Each widget owns its namespace.

### Step 5: No regression

**Do:** Pin a session (sticky), collapse another, expand a todo, toggle animation mode. SIGUSR2 reload.
**Observe:** All state survives — sticky sessions, collapsed sessions, expanded todos, animation mode.
**Why:** Existing persistence migrated to the same Persistable protocol without loss.
