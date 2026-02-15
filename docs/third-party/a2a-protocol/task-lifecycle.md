# A2A Task Lifecycle

## What it is

A Task is the stateful unit of work in A2A. Tasks are created implicitly when a client sends a message, progress through defined states, and produce Artifacts as output.

## Task States

```
              +-- input_required <--+
              |                     |
submitted --> working ------------> completed
              |                     |
              +-- auth_required     +-> failed
              |                     +-> canceled
              +---------------------> rejected
```

| State            | Terminal | Description                              |
| ---------------- | -------- | ---------------------------------------- |
| `submitted`      | no       | Task created, acknowledged by server     |
| `working`        | no       | Actively being processed                 |
| `input_required` | no       | Agent needs additional input from client |
| `auth_required`  | no       | Requires out-of-band authentication      |
| `completed`      | yes      | Successfully finished                    |
| `failed`         | yes      | Error during execution                   |
| `canceled`       | yes      | Client requested cancellation            |
| `rejected`       | yes      | Agent declined to process                |

Terminal tasks cannot be restarted. Sending a message to a terminal task returns an error.

## Task Object

```json
{
  "id": "task-uuid-123",
  "contextId": "ctx-conversation-abc",
  "status": {
    "state": "working",
    "timestamp": "2025-04-02T16:59:25Z"
  },
  "history": [
    {
      "role": "user",
      "parts": [{ "kind": "text", "text": "Generate a report on Q1 sales" }],
      "messageId": "msg-001"
    }
  ],
  "artifacts": []
}
```

## Artifact Object

Artifacts are task outputs, composed of Parts:

```json
{
  "artifactId": "artifact-001",
  "name": "q1-sales-report.pdf",
  "description": "Q1 2025 sales analysis",
  "parts": [
    {
      "kind": "file",
      "file": {
        "name": "report.pdf",
        "mediaType": "application/pdf",
        "data": "base64-encoded-content"
      }
    }
  ]
}
```

Streaming artifacts use `append: true` and `lastChunk: true/false` for incremental delivery.

## Context Grouping

The `contextId` field groups related tasks into a conversation. Multiple tasks can share a context, enabling:

- Multi-turn interactions where follow-up tasks reference prior context
- Parallel task execution within the same conversation
- History tracking across related work items

## Message Parts

| Part Kind | Fields                                                   | Use                                           |
| --------- | -------------------------------------------------------- | --------------------------------------------- |
| `text`    | `text`                                                   | Plain text content                            |
| `file`    | `file.name`, `file.mediaType`, `file.data` or `file.uri` | File content (inline base64 or URI reference) |
| `data`    | `data`, `mediaType`                                      | Structured data (JSON, etc.)                  |

## Sources

- https://a2a-protocol.org/latest/specification
- https://a2a-protocol.org/latest/topics/life-of-a-task
- /websites/a2a-protocol
- /google/a2a
