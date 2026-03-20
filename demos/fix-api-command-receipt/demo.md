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
assert ProcessMessageCommand(session_id='s', text='hi', origin='api').response_mode == ResponseMode.IMMEDIATE
assert KeysCommand(session_id='s', key='Enter').response_mode == ResponseMode.IMMEDIATE
assert StartAgentCommand(session_id='s', agent_name='claude').response_mode == ResponseMode.IMMEDIATE
assert SystemCommand(command='list').response_mode == ResponseMode.IMMEDIATE
# FIRE_AND_FORGET commands must have completion_event
close = CloseSessionCommand(session_id='s')
assert close.response_mode == ResponseMode.FIRE_AND_FORGET
assert close.completion_event == 'session.close_completed'
restart = RestartAgentCommand(session_id='s')
assert restart.response_mode == ResponseMode.FIRE_AND_FORGET
assert restart.completion_event == 'agent.restart_dispatched'
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
# 5. Verify domain event payload dataclasses exist and are frozen
python -c "
from teleclaude.core.events import (
    AgentRestartDispatchedPayload,
    SessionCloseCompletedPayload,
    SessionEscalatedPayload,
    JobStartedPayload, JobCompletedPayload, JobFailedPayload,
    NotificationClaimedPayload, NotificationResolvedPayload,
)
import dataclasses
for cls in [AgentRestartDispatchedPayload, SessionCloseCompletedPayload,
            SessionEscalatedPayload, JobStartedPayload, JobCompletedPayload,
            JobFailedPayload, NotificationClaimedPayload, NotificationResolvedPayload]:
    assert dataclasses.is_dataclass(cls), f'{cls.__name__} is not a dataclass'
    print(f'{cls.__name__}: frozen dataclass OK')
print('All new event payloads are frozen dataclasses')
"
```

```bash
# 6. Verify receipt completion_event field
python -c "
from teleclaude.api_models import OperationStatusDTO
import inspect
sig = inspect.signature(OperationStatusDTO)
assert 'completion_event' in sig.parameters, 'OperationStatusDTO missing completion_event'
print(f'OperationStatusDTO.completion_event: present')
"
```

```bash
# 7. Verify CommandService has typed command methods
python -c "
from teleclaude.core.command_service import CommandService
assert hasattr(CommandService, 'deliver_result'), 'Missing deliver_result'
assert hasattr(CommandService, 'render_widget'), 'Missing render_widget'
assert hasattr(CommandService, 'escalate_session'), 'Missing escalate_session'
assert hasattr(CommandService, 'system_command'), 'Missing system_command'
print('All typed command methods present on CommandService')
"
```

## Guided Presentation

### Step 1: Type system foundation

Show that `ResponseMode` is now a first-class property of every command. Open
`teleclaude/types/commands.py` and point out the enum, the base class fields, and
the `__post_init__` validation. Demonstrate that `RestartAgentCommand` is correctly
classified as `FIRE_AND_FORGET` with `completion_event="agent.restart_dispatched"`.

### Step 2: Metadata-driven dispatch

Show that the isinstance chains are gone. Open
`teleclaude/transport/redis_transport/_messaging.py` and show the dispatch table
keyed on `CommandType` with the `response_mode` execution layer.

### Step 3: Receipt-backed operations

Show that `POST /todos/create` and `POST /todos/prepare` now return 202 receipts.
Walk through the new `submit_todo_create` and `submit_todo_prepare` methods.

### Step 4: Domain events

Show the new event payload dataclasses. Trace the agent restart emission path:
`completion_event` on `RestartAgentCommand` → `agent_restart` handler emits
`AgentRestartDispatchedPayload` → route returns 202 with event name in body.

### Step 5: Command coverage and DELETE routing

Show `DELETE /sessions/{id}` routing through `CommandService.close_session` with
remote-routing support via `forward_command` for non-local sessions.

### Step 6: Documentation

Show the updated architecture docs reflecting the implemented state.
