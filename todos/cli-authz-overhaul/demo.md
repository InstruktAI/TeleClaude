# Demo: cli-authz-overhaul

## Validation

```bash
# Verify every leaf command in CLI_SURFACE has auth metadata populated
python3 -c "
from teleclaude.cli.telec import CLI_SURFACE, CommandDef

def count_leaves(surface, prefix=''):
    total = 0
    missing = []
    for name, cmd in surface.items():
        path = f'{prefix}{name}'
        if cmd.subcommands:
            t, m = count_leaves(cmd.subcommands, f'{path} ')
            total += t
            missing.extend(m)
        else:
            total += 1
            if cmd.auth is None:
                missing.append(path)
    return total, missing

total, missing = count_leaves(CLI_SURFACE)
assert not missing, f'Leaf commands without auth: {missing}'
print(f'All {total} leaf commands have auth metadata.')
"
```

```bash
# Verify is_command_allowed() exists and handles basic cases
python3 -c "
from teleclaude.cli.telec import is_command_allowed

# Admin can do everything except escalate
assert is_command_allowed('sessions start', None, 'admin') == True
assert is_command_allowed('sessions escalate', None, 'admin') == False

# Worker restrictions
assert is_command_allowed('sessions start', 'worker', 'admin') == False
assert is_command_allowed('sessions result', 'worker', 'admin') == True

# Customer restrictions (only version, docs, auth, escalate)
assert is_command_allowed('version', None, 'customer') == True
assert is_command_allowed('docs index', None, 'customer') == True
assert is_command_allowed('sessions escalate', 'worker', 'customer') == True
assert is_command_allowed('sessions start', None, 'customer') == False
assert is_command_allowed('roadmap list', None, 'customer') == False

# None human_role = deny
assert is_command_allowed('sessions start', None, None) == False

print('All authorization checks passed.')
"
```

```bash
# Run the full test suite
make test
```

## Guided Presentation

### Step 1: The CommandAuth model

Open `teleclaude/cli/telec.py` and show the new `CommandAuth` dataclass. Point out:
- `system` field: allowed system roles (worker/orchestrator).
- `human` field: allowed human roles (admin is always implicit except for escalate).
- The `exclude_human` field: explicitly excludes a role (used for admin on escalate).

### Step 2: Auth metadata on CLI_SURFACE

Show a few representative `CommandDef` entries with their `auth` field:
- `sessions start`: orchestrator-only, admin + member.
- `sessions escalate`: all system roles, all non-admins, admin excluded.
- `docs index`: universal access.
- `config wizard`: orchestrator, admin only.

Observe: the authorization decision is declared right where the command is defined. No separate
deny-list file. No scattered constants. The command describes its own access.

### Step 3: `is_command_allowed()` function

Show the function. Walk through the composition rule:
1. Resolve command path to its `CommandAuth`.
2. Check system role: is the caller's system role in `auth.system`?
3. Check human role: is the caller admin (and not excluded)? Or is the caller's role in `auth.human`?
4. Both must pass.

### Step 4: Completeness guarantee

Show the unit test that walks all leaf commands and asserts `auth is not None`. This prevents
future regressions when new commands are added without thinking about authorization.

### Step 5: What comes next

Explain that this is the foundation. Follow-on workstreams will:
- Wire the API to use `is_command_allowed()` instead of legacy deny-lists (WS8).
- Delete `tool_access.py` and `CLEARANCE_*` constants (WS2).
- Filter `telec -h` output by caller role (WS3).
- Make session roles mandatory and kill the heuristic (WS4).
