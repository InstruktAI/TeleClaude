# Demo: icebox-physical-folder

## Validation

```bash
# Run the one-time migration (safe to re-run)
telec roadmap migrate-icebox
```

```bash
# Verify _icebox directory exists and contains icebox.yaml
test -f todos/_icebox/icebox.yaml && echo "PASS: icebox.yaml relocated" || echo "FAIL"
```

```bash
# Verify no frozen folders remain in todos/ root
.venv/bin/python3 -c "
import yaml
from pathlib import Path
icebox = yaml.safe_load(open('todos/_icebox/icebox.yaml'))
slugs = {e['slug'] for e in icebox}
groups = {e.get('group') for e in icebox if e.get('group')}
stray = [s for s in slugs | groups if (Path('todos') / s).exists()]
print(f'Stray folders in todos/: {stray}' if stray else 'PASS: todos/ is clean')
"
```

```bash
# Verify freeze moves folder
telec roadmap add demo-freeze-test --description "Temp demo"
telec todo create demo-freeze-test
telec roadmap freeze demo-freeze-test
test -d todos/_icebox/demo-freeze-test && echo "PASS: freeze moved folder" || echo "FAIL"
test ! -d todos/demo-freeze-test && echo "PASS: source removed" || echo "FAIL"
```

```bash
# Verify unfreeze restores folder
telec roadmap unfreeze demo-freeze-test
test -d todos/demo-freeze-test && echo "PASS: unfreeze restored folder" || echo "FAIL"
test ! -d todos/_icebox/demo-freeze-test && echo "PASS: icebox source removed" || echo "FAIL"
```

```bash
# Verify removal from icebox location
telec roadmap freeze demo-freeze-test
telec todo remove demo-freeze-test
test ! -d todos/_icebox/demo-freeze-test && echo "PASS: removed from icebox" || echo "FAIL"
```

```bash
# Verify orphan scan does not list _icebox
telec roadmap list 2>&1 | grep -c "_icebox" | xargs -I{} test {} -eq 0 && echo "PASS: _icebox not orphan" || echo "FAIL"
```

```bash
# Run the targeted proving set
.venv/bin/pytest tests/unit/core/test_roadmap.py tests/unit/core/test_roadmap_api_parity.py tests/unit/test_todo_scaffold.py tests/unit/test_telec_cli.py tests/unit/test_teleclaude_events/test_prepare_quality.py
```

## Guided Presentation

### Step 1 — The problem

Before this change, `todos/` contained 17 frozen folders mixed in with active work.
The TUI hid them via `assemble_roadmap` filtering, but they cluttered the workspace
for anyone browsing the filesystem.

### Step 2 — Migration

Run `telec roadmap migrate-icebox`. This moves all 17 frozen folders (16 slugs + 1
group container) into `todos/_icebox/` and relocates `icebox.yaml` alongside them.
The migration is idempotent — running it again returns 0.

Observe: `ls todos/` now shows only active/pending work. `ls todos/_icebox/` shows
all frozen items with their `icebox.yaml` manifest.

### Step 3 — Freeze with folder move

Create a test item, add to roadmap, then freeze it. The folder moves from `todos/`
to `todos/_icebox/` alongside the YAML update. This keeps physical location and
metadata in sync.

### Step 4 — Unfreeze (new command)

`telec roadmap unfreeze <slug>` is the reverse: removes from `icebox.yaml`, appends
to `roadmap.yaml`, and moves the folder back to `todos/`. The unfrozen item appears
at the bottom of the roadmap (lowest priority).

### Step 5 — Clean removal

`telec todo remove` now checks both `todos/{slug}` and `todos/_icebox/{slug}`, so
frozen items can be removed without unfreezing first.

### Step 6 — Orphan scan

`telec roadmap list` no longer reports `_icebox` as an orphan. The exclusion uses
`== "_icebox"` (not `startswith("_")`) so other underscore-prefixed directories are
not accidentally hidden.
