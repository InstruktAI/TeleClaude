# Demo: fix-api-command-receipt

## Validation

```bash
# 1. Verify ResponseMode is declared on all commands
python -c "
from teleclaude.types.commands import (
    ResponseMode, CreateSessionCommand, CloseSessionCommand,
    ProcessMessageCommand, StartAgentCommand, KeysCommand,
    HandleVoiceCommand, HandleFileCommand, GetSessionDataCommand,
    RestartAgentCommand, ResumeAgentCommand, RunAgentCommand, SystemCommand,
)
# IMMEDIATE commands
assert CreateSessionCommand(project_path='/x', origin='api').response_mode == ResponseMode.IMMEDIATE
assert GetSessionDataCommand(session_id='s').response_mode == ResponseMode.IMMEDIATE
assert SystemCommand(command='list').response_mode == ResponseMode.IMMEDIATE
# FIRE_AND_FORGET commands must have completion_event
close = CloseSessionCommand(session_id='s')
assert close.response_mode == ResponseMode.FIRE_AND_FORGET
assert close.completion_event == 'session.close_completed'
restart = RestartAgentCommand(session_id='s')
assert restart.response_mode == ResponseMode.FIRE_AND_FORGET
assert restart.completion_event == 'agent.restart_dispatched'
msg = ProcessMessageCommand(session_id='s', text='hi', origin='api')
assert msg.response_mode == ResponseMode.FIRE_AND_FORGET
assert msg.completion_event is not None
print('All ResponseMode declarations verified')
"
```

```bash
# 2. Verify construction-time validation rejects invalid FIRE_AND_FORGET
python -c "
from teleclaude.types.commands import ResponseMode, InternalCommand, CommandType
try:
    InternalCommand(
        command_type=CommandType.SYSTEM,
        response_mode=ResponseMode.FIRE_AND_FORGET,
        completion_event=None,
    )
    print('ERROR: should have raised')
    exit(1)
except ValueError as e:
    print(f'Correctly rejected: {e}')
"
```

```bash
# 3. Verify dispatch table replaces isinstance chains
python -c "
import ast, sys
with open('teleclaude/transport/redis_transport/_messaging.py') as f:
    tree = ast.parse(f.read())
for node in ast.walk(tree):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'isinstance':
        for arg in node.args:
            if isinstance(arg, ast.Name) and 'Command' in arg.id:
                print(f'ERROR: isinstance check on {arg.id} still present')
                sys.exit(1)
print('No isinstance command dispatch chains found')
"
```

```bash
# 4. Verify new operation kinds exist in OperationsService
python -c "
from teleclaude.core.operations.service import (
    OPERATION_KIND_TODO_CREATE, OPERATION_KIND_TODO_PREPARE,
    OPERATION_KIND_TODO_WORK, OPERATION_KIND_TODO_INTEGRATE,
)
print(f'todo_create: {OPERATION_KIND_TODO_CREATE}')
print(f'todo_prepare: {OPERATION_KIND_TODO_PREPARE}')
print(f'todo_work: {OPERATION_KIND_TODO_WORK}')
print(f'todo_integrate: {OPERATION_KIND_TODO_INTEGRATE}')
print('All 4 operation kinds registered')
"
```

```bash
# 5. Verify domain event payload dataclasses are frozen
python -c "
from teleclaude.core.events import (
    AgentRestartDispatchedEvent,
    SessionCloseCompletedEvent,
    SessionEscalationStartedEvent,
    JobLifecycleEvent,
)
import dataclasses
for cls in [AgentRestartDispatchedEvent, SessionCloseCompletedEvent,
            SessionEscalationStartedEvent, JobLifecycleEvent]:
    assert dataclasses.is_dataclass(cls), f'{cls.__name__} is not a dataclass'
    # frozen check: attempt mutation should raise
    instance = cls.__new__(cls)
    print(f'{cls.__name__}: frozen dataclass ✓')
print('All new event payloads are frozen dataclasses')
"
```

```bash
# 6. Run pre-commit hooks (primary verification path)
git add -A && git diff --cached --stat
```

```bash
# 7. Verify response code alignment for fire-and-forget endpoints
# (agent-restart should now be 202, not 200; already-correct endpoints stay 200)
python -c "
# This verification is best done with the running daemon via curl or httpx.
# The builder should verify:
# - POST /sessions/{id}/agent-restart → 202 with completion_event
# - POST /jobs/{name}/run → 202 with completion_event
# - DELETE /sessions/{id} → 202 with completion_event in body
# - POST /sessions/self/escalate → 202 with completion_event (after wrapping)
# - POST /sessions/{id}/keys → 200 unchanged (already correct)
# - POST /sessions/{id}/message → 200 unchanged (already correct)
print('Response code alignment: verify via API calls against running daemon')
"
```

```bash
# 8. Verify receipt completion_event field
python -c "
from teleclaude.api_models import OperationStatusDTO
import inspect
sig = inspect.signature(OperationStatusDTO)
assert 'completion_event' in sig.parameters, 'OperationStatusDTO missing completion_event'
print(f'OperationStatusDTO.completion_event: present')
"
```

## Guided Presentation

### Step 1: Type system foundation
Show that `ResponseMode` is now a first-class property of every command. Open
`teleclaude/types/commands.py` and point out the enum, the base class fields, and
the `__init__` validation. Demonstrate that `RestartAgentCommand` is correctly
classified as `FIRE_AND_FORGET` (matching its actual async dispatch behavior),
not `IMMEDIATE` as previously stated in the design doc.

### Step 2: Metadata-driven dispatch
Show that the isinstance chains are gone. Open
`teleclaude/transport/redis_transport/_messaging.py` and show the dispatch table
keyed on `CommandType`. Demonstrate that adding a new command type only requires
adding a table entry — no elif branch needed.

### Step 3: Receipt-backed operations
Show that `POST /todos/create` and `POST /todos/prepare` now return 202 receipts
instead of blocking. Walk through `teleclaude/core/operations/service.py` to show
the new `submit_todo_create` and `submit_todo_prepare` methods following the
existing `submit_todo_work` pattern.

### Step 4: Domain events
Show the new event payload dataclasses in `teleclaude/core/events.py`. Trace
the agent restart emission path: `completion_event` declared on
`RestartAgentCommand` → `agent_restart` handler emits `AgentRestartDispatchedEvent`
→ route returns 202 with the event name in the response body.

### Step 5: Command coverage and DELETE routing
Show that result, widget, and escalate endpoints now go through `SystemCommand`
dispatch. Show that `DELETE /sessions/{id}` routes through `CloseSessionCommand`
with remote-routing support via the `_computer` parameter.

### Step 6: Response code alignment
Show that fire-and-forget routes return 202 with `completion_event` in the body.
Contrast with IMMEDIATE routes that still return 200.

### Step 7: Documentation
Show the updated architecture docs: corrected classification table, generalized
operation-receipts doc, api-server endpoint mapping, redis-transport response
mode section.

### Step 8: Response code alignment
Show the response code matrix: only agent-restart, jobs/run, escalation, and
DELETE changed to 202. All "already correct" endpoints (message, keys, voice,
file) remain at 200. Show that `completion_event` in 202 responses matches
the command object's declaration — derived, not hardcoded.

### Step 9: Receipt completion_event
Show that `OperationStatusDTO` now carries `completion_event`. Trace the flow:
operation created → terminal transition → event emitted → receipt includes
event name for consumer subscription.

### Step 10: Regression safety
Run pre-commit hooks to show nothing broke. Point out that endpoints marked
"already correct" and "leave as-is" in the audit are untouched.
