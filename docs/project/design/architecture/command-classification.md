---
description: 'Response-mode classification for API commands: immediate, fire-and-forget, and receipt-backed async.'
id: 'project/design/architecture/command-classification'
scope: 'project'
type: 'design'
---

# Command Classification — Design

## Purpose

Every mutating API endpoint maps to one of three response modes. The mode is a property
of the command, not of the route — it lives on the `InternalCommand` base class and is
declared by each command subclass. API routes, the transport layer, and the command
dispatcher all read this property; they do not re-derive it from `isinstance` checks or
hardcoded status codes.

```mermaid
flowchart TD
    Request["HTTP Request"]
    Router["API Route"]
    Command["InternalCommand\n(response_mode declared)"]
    Service["CommandService"]

    Request --> Router
    Router --> Command
    Command -->|IMMEDIATE| Service
    Command -->|FIRE_AND_FORGET| Service
    Command -->|RECEIPT| Service

    Service -->|returns data| ImmediateResp["200 + payload"]
    Service -->|emits event, returns nothing| FFResp["202 accepted\n+ completion_event"]
    Service -->|persists operation row| ReceiptResp["202 + receipt"]
```

## Inputs/Outputs

**Inputs:** Any HTTP mutation request (POST, PUT, PATCH, DELETE) routed through CommandService.

**Outputs per mode:**

- `IMMEDIATE` — `200 OK` with the command result in the body.
- `FIRE_AND_FORGET` — `202 Accepted` with `{status: "accepted", completion_event: "<domain.event>"}`.
- `RECEIPT` — `202 Accepted` with a full `OperationReceipt` (see below).

## Invariants

- **Mode lives on the command.** No route may hardcode a status code that contradicts the
  command's declared `response_mode`. The route reads the mode and derives the status code
  from it.
- **Dispatcher reads mode, not type.** `_dispatch_command()` must not use `isinstance`
  chains to decide whether to capture a return value. It reads `command.response_mode`.
- **Atomic terminal transition.** When a RECEIPT operation reaches a terminal state
  (`completed` | `failed` | `stale`), the `OperationsService` emits the `completion_event`
  as the final step of marking the row terminal. The event and the DB row transition are
  never split across separate code paths.
- **completion_event is required for FIRE_AND_FORGET.** Every command with mode
  `FIRE_AND_FORGET` must declare a `completion_event` string. Leaving it `None` is a
  contract violation and a startup assertion failure.
- **completion_event is informational, not a dispatch key.** Call sites that receive
  a receipt or a 202 response may use `completion_event` for tracing, monitoring, and
  test harnesses. They must not use it to dynamically deserialize payloads — payload
  semantics are expressed in static types.

## Primary flows

### 1. IMMEDIATE command

```mermaid
sequenceDiagram
    participant Client
    participant Route
    participant CommandService
    participant Handler

    Client->>Route: POST /sessions
    Route->>CommandService: CreateSessionCommand(response_mode=IMMEDIATE)
    CommandService->>Handler: dispatch
    Handler->>CommandService: {session_id, ...}
    CommandService->>Route: result
    Route->>Client: 200 OK + result
```

Commands in this mode: `CreateSessionCommand`, `RestartAgentCommand`, `GetSessionDataCommand`.

### 2. FIRE_AND_FORGET command

```mermaid
sequenceDiagram
    participant Client
    participant Route
    participant CommandService
    participant Handler
    participant EventBus

    Client->>Route: DELETE /sessions/{id}
    Route->>CommandService: CloseSessionCommand(response_mode=FIRE_AND_FORGET)
    CommandService->>Handler: dispatch
    Handler->>EventBus: emit SESSION_CLOSE_REQUESTED
    CommandService->>Route: None
    Route->>Client: 202 Accepted\n{completion_event: "session.close_completed"}
    EventBus-->>Client: WS push: session.close_completed
```

Commands in this mode: `CloseSessionCommand`, `ProcessMessageCommand`, `StartAgentCommand`,
`ResumeAgentCommand`, `RunAgentCommand`, `KeysCommand`, `HandleVoiceCommand`, `HandleFileCommand`.

### 3. RECEIPT command

```mermaid
sequenceDiagram
    participant Client
    participant Route
    participant OperationsService
    participant BackgroundTask
    participant DB
    participant EventBus

    Client->>Route: POST /todos/work
    Route->>OperationsService: submit(kind, response_mode=RECEIPT)
    OperationsService->>DB: persist operation row (state=queued)
    OperationsService->>Route: OperationReceipt
    Route->>Client: 202 Accepted + receipt
    BackgroundTask->>DB: claim + heartbeat (state=running)
    BackgroundTask->>DB: terminal result (state=completed)
    BackgroundTask->>EventBus: emit completion_event
    Client->>Route: GET /operations/{id}
    Route->>Client: {state: "completed", result: ...}
```

Commands in this mode: `TodoWorkCommand`, `TodoIntegrateCommand`, `TodoCreateCommand`,
`TodoPrepareCommand`.

## Inputs/Outputs

### `ResponseMode` enum

```python
class ResponseMode(str, Enum):
    IMMEDIATE       = "immediate"        # sync result returned in response body
    FIRE_AND_FORGET = "fire_and_forget"  # async work, event signals completion
    RECEIPT         = "receipt"          # durable operation row, polling + event
```

### `InternalCommand` base fields

```python
@dataclass(kw_only=True)
class InternalCommand:
    command_type:     CommandType
    request_id:       str | None      = None
    response_mode:    ResponseMode    = ResponseMode.IMMEDIATE
    completion_event: str | None      = None  # required when response_mode != IMMEDIATE
```

### `OperationReceipt` fields (RECEIPT mode response)

```python
{
  "operation_id":       str,       # durable identity
  "kind":               str,       # operation kind (e.g. "todo_work")
  "state":              str,       # queued | running | completed | failed | stale
  "status_path":        str,       # /operations/{operation_id}
  "poll_after_ms":      int,       # suggested polling interval (0 if terminal)
  "completion_event":   str,       # domain event emitted on terminal transition
  "recovery_command":   str,       # telec operations get {operation_id}
}
```

### FIRE_AND_FORGET 202 response fields

```python
{
  "status":             "accepted",
  "completion_event":   str,       # domain event name to listen for
}
```

## Failure modes

- **Mode mismatch between route and command.** If a route assumes 200 but the command
  declares FIRE_AND_FORGET, the client receives the wrong status code. The dispatcher
  asserts `response_mode` consistency at dispatch time.
- **RECEIPT operation lost on daemon restart.** Background tasks are not replayed.
  Queued or running operations are marked `stale` at startup. Clients polling the
  receipt see `state: "stale"` and may resubmit.
- **completion_event never fires.** If the background task panics before the terminal
  DB write, the event is not emitted and polling clients eventually see the stale
  heartbeat window expire. The receipt remains the source of truth; the event is
  a convenience, not the authority.
- **FIRE_AND_FORGET with no completion_event declared.** Assertion failure at startup.
  No command may ship with `response_mode=FIRE_AND_FORGET` and `completion_event=None`.

