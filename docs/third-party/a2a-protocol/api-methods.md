# A2A API Methods

## What it is

A2A uses JSON-RPC 2.0 over HTTP for all interactions. The base endpoint is typically `/a2a/v1` or the URL specified in the Agent Card's `interfaces` field. gRPC is also supported since v0.3.

## Methods

### Message Operations

#### SendMessage

Initiate a task or continue an existing conversation. Returns a Task or Message.

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{ "kind": "text", "text": "Search for flights to Tokyo" }],
      "messageId": "msg-001"
    },
    "configuration": {
      "blocking": true
    }
  }
}
```

Response contains either `task` (stateful work) or `message` (direct response).

#### SendStreamingMessage

Same as SendMessage but returns SSE stream for real-time updates. Requires `capabilities.streaming: true`.

**Endpoint:** `POST /v1/message:stream`

SSE events:

```
data: {"task": {"id": "task-123", "status": {"state": "submitted"}}}
data: {"statusUpdate": {"taskId": "task-123", "status": {"state": "working"}}}
data: {"artifactUpdate": {"taskId": "task-123", "artifact": {"parts": [{"text": "..."}]}, "append": false, "lastChunk": false}}
data: {"artifactUpdate": {"taskId": "task-123", "artifact": {"parts": [{"text": "..."}]}, "append": true, "lastChunk": true}}
data: {"statusUpdate": {"taskId": "task-123", "status": {"state": "completed"}, "final": true}}
```

### Task Management

| Method            | Purpose                                   |
| ----------------- | ----------------------------------------- |
| `GetTask`         | Retrieve current task state by ID         |
| `ListTasks`       | Query tasks with filtering and pagination |
| `CancelTask`      | Request cancellation of a running task    |
| `SubscribeToTask` | Stream updates for an existing task       |

### Push Notifications

For long-running or disconnected scenarios. Requires `capabilities.pushNotifications: true`.

| Method                             | Purpose                               |
| ---------------------------------- | ------------------------------------- |
| `CreateTaskPushNotificationConfig` | Register webhook URL for task updates |
| `GetTaskPushNotificationConfig`    | Retrieve notification config          |
| `ListTaskPushNotificationConfig`   | List all configs for a task           |
| `DeleteTaskPushNotificationConfig` | Remove notification config            |

Push notification request:

```json
{
  "configuration": {
    "pushNotificationConfig": {
      "url": "https://client.example.com/webhook/a2a",
      "token": "client-verification-token",
      "authentication": { "schemes": ["Bearer"] }
    }
  }
}
```

Server POSTs updates to the webhook:

```json
{
  "statusUpdate": {
    "taskId": "task-123",
    "status": { "state": "completed" },
    "final": true
  }
}
```

### Discovery

| Method                             | Purpose                                            |
| ---------------------------------- | -------------------------------------------------- |
| `GET /.well-known/agent-card.json` | Public Agent Card                                  |
| `GetExtendedAgentCard`             | Authenticated extended card with full capabilities |

## Error Handling

Standard JSON-RPC error responses with A2A-specific codes for task state violations (e.g., sending to a terminal task).

## Sources

- https://a2a-protocol.org/latest/specification
- /websites/a2a-protocol
- /google/a2a
