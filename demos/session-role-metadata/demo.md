# Demo: session-role-metadata

## Validation

### 1. Integrator CommandAuth — allowed and blocked commands

```bash
python3 -c "
from teleclaude.cli.telec import is_command_allowed
from teleclaude.constants import ROLE_INTEGRATOR, HUMAN_ROLE_MEMBER
# Integrator can drive integration
assert is_command_allowed('todo integrate', ROLE_INTEGRATOR, HUMAN_ROLE_MEMBER), 'should allow integrate'
# Integrator cannot dispatch workers
assert not is_command_allowed('sessions run', ROLE_INTEGRATOR, HUMAN_ROLE_MEMBER), 'should block dispatch'
# Integrator cannot use orchestrator commands
assert not is_command_allowed('todo work', ROLE_INTEGRATOR, HUMAN_ROLE_MEMBER), 'should block work'
print('Integrator CommandAuth OK')
"
```

### 2. Auth derivation recognizes integrator

```bash
python3 -c "
from types import SimpleNamespace
from teleclaude.api.auth import _derive_session_system_role
session = SimpleNamespace(session_metadata={'system_role': 'integrator'}, working_slug=None)
role = _derive_session_system_role(session)
assert role == 'integrator', f'expected integrator, got {role}'
print(f'Auth derivation OK: {role}')
"
```

### 3. Command role map covers lifecycle commands

```bash
python3 -c "
from teleclaude.api_server import COMMAND_ROLE_MAP
assert COMMAND_ROLE_MAP['next-integrate'] == ('integrator', 'integrator')
assert COMMAND_ROLE_MAP['next-build'] == ('worker', 'builder')
assert COMMAND_ROLE_MAP['next-work'] == ('orchestrator', 'work-orchestrator')
print(f'COMMAND_ROLE_MAP OK ({len(COMMAND_ROLE_MAP)} entries)')
"
```

### 4. CLI CommandAuth includes integrator for whitelisted commands

```bash
python3 -c "
from teleclaude.cli.telec import is_command_allowed
from teleclaude.constants import ROLE_INTEGRATOR, HUMAN_ROLE_MEMBER
# Integrator can call todo integrate
assert is_command_allowed('todo integrate', ROLE_INTEGRATOR, HUMAN_ROLE_MEMBER)
# Integrator cannot call todo work
assert not is_command_allowed('todo work', ROLE_INTEGRATOR, HUMAN_ROLE_MEMBER)
# Integrator can list sessions
assert is_command_allowed('sessions list', ROLE_INTEGRATOR, HUMAN_ROLE_MEMBER)
# Integrator cannot send messages
assert not is_command_allowed('sessions send', ROLE_INTEGRATOR, HUMAN_ROLE_MEMBER)
print('CommandAuth integrator OK')
"
```

### 5. Job filter flag documented in CLI

```bash
telec sessions list --help 2>&1 | grep -q -- '--job' && echo '--job flag present in help' || echo 'MISSING --job flag'
```

## Guided Presentation

### Step 1: The problem — dead integrator sessions block new spawns

Before this change, the integrator spawn guard checked for running integrators by
grepping `"integrator" in stdout` of `telec sessions list`. If a dead session had
"integrator" in its title, no new integrator could ever spawn. There was also no
permission profile — the integrator ran with orchestrator-level permissions.

### Step 2: Integrator is now a first-class role

Show that `ROLE_INTEGRATOR` exists as a constant, is recognized by the auth derivation
layer, and its permissions are defined via CLI_SURFACE CommandAuth entries. The integrator
can observe sessions, report results, and drive integration — but cannot dispatch sessions
or mark phases. `is_command_allowed()` is now the single source of truth for daemon auth
(replacing the legacy `is_tool_allowed()` and hardcoded exclusion sets).

### Step 3: Server-side metadata derivation

When `telec sessions run --command /next-integrate` is called, the server looks up
`COMMAND_ROLE_MAP["next-integrate"]` and injects `system_role=integrator, job=integrator`
into `session_metadata`. No caller can override this — the command IS the role.

### Step 4: Structured spawn guard

The integration bridge now queries `telec sessions list --all --job integrator` and
parses JSON. Only sessions with `session_metadata.job == "integrator"` block spawning.
Dead sessions without metadata no longer cause false positives. The spawn itself uses
`telec sessions run --command /next-integrate` so the server derives integrator identity.

### Step 5: CLI alignment

`telec sessions list --job integrator` filters sessions by job metadata. The `todo integrate`
command is accessible to integrator-role sessions. All other orchestrator-only commands
remain blocked.
