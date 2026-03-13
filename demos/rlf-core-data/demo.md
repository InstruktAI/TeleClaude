# Demo: rlf-core-data

## Validation

Verify the three large data-layer files are decomposed into packages and all imports still work.

```bash
# Confirm db.py is gone and db/ package exists
test ! -f teleclaude/core/db.py && echo "db.py deleted ✓"
test -d teleclaude/core/db && echo "db/ package exists ✓"
ls teleclaude/core/db/
```

```bash
# Confirm command_handlers.py is gone and package exists
test ! -f teleclaude/core/command_handlers.py && echo "command_handlers.py deleted ✓"
test -d teleclaude/core/command_handlers && echo "command_handlers/ package exists ✓"
ls teleclaude/core/command_handlers/
```

```bash
# Confirm models.py is gone and package exists
test ! -f teleclaude/core/models.py && echo "models.py deleted ✓"
test -d teleclaude/core/models && echo "models/ package exists ✓"
ls teleclaude/core/models/
```

```bash
# Verify all existing import paths still work via __init__.py re-exports
.venv/bin/python -c "
from teleclaude.core.db import db, Db, get_session_id_by_tmux_name_sync, resolve_session_principal
from teleclaude.core.command_handlers import create_session, start_agent, process_message, with_session
from teleclaude.core.models import Session, SessionSnapshot, StartSessionArgs, ThinkingMode
print('All public imports: OK')
"
```

```bash
# Verify no module exceeds 800 lines (hard ceiling per requirements)
python3 -c "
import os, sys
violations = []
for root, dirs, files in os.walk('teleclaude/core/db'):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            lines = open(path).read().count('\n')
            if lines > 800:
                violations.append(f'{path}: {lines} lines')
for root, dirs, files in os.walk('teleclaude/core/command_handlers'):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            lines = open(path).read().count('\n')
            if lines > 800:
                violations.append(f'{path}: {lines} lines')
for root, dirs, files in os.walk('teleclaude/core/models'):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            lines = open(path).read().count('\n')
            if lines > 800:
                violations.append(f'{path}: {lines} lines')
if violations:
    print('VIOLATIONS:', violations)
    sys.exit(1)
else:
    print('All modules within 800-line ceiling: OK')
"
```

```bash
# Run tests to confirm no regressions
.venv/bin/pytest tests/ -x -q --tb=short 2>&1 | tail -5
```

## Guided Presentation

1. Show the three new packages with `ls teleclaude/core/db/ teleclaude/core/command_handlers/ teleclaude/core/models/`.
2. Demonstrate that all existing imports work via the python import check above.
3. Show module sizes are all under 800 lines.
4. Run the test suite to confirm 139 tests pass with no regressions.
