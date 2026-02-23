# Demo: deployment-auto-update

## Validation

```bash
# Update executor module exists
python -c "from teleclaude.deployment.update_executor import check_for_update, execute_update; print('OK')"
```

```bash
# Signal file detection works
python -c "
from teleclaude.deployment.update_executor import check_for_update
result = check_for_update()
# None when no signal file exists
assert result is None
print('OK: no signal = no update')
"
```

## Guided Presentation

### Step 1: Signal file detection

Show that without `~/.teleclaude/update_available.json`, `check_for_update()`
returns None. No action taken.

### Step 2: Mock an available update

Create a signal file: `{"current": "1.0.0", "available": "1.1.0", "channel": "beta"}`.
Show that `check_for_update()` now returns the update info.

### Step 3: Update sequence walkthrough

Explain the execution order: fetch code -> run migrations -> make install ->
remove signal file -> restart (exit 42). Show the logging at each step.

### Step 4: Failure handling

Demonstrate that if migration fails, the update halts — no restart is triggered,
Redis status shows "update_failed", signal file is preserved for retry.

### Step 5: Redis status

Show Redis status key `system_status:{computer}:deploy` progression during
update: checking -> updating -> migrating -> installing -> restarting.
