---
id: 'project/spec/messaging'
type: 'spec'
scope: 'project'
description: 'Messaging tools for Telegram, Discord, and email delivery — hooks, files, widgets, and escalation.'
---

# Messaging — Spec

## What it is

TeleClaude exposes several messaging tools for agents to deliver content to users and external systems. All tools operate through the daemon's Unix socket API (`/tmp/teleclaude-api.sock`) or MCP tool interface.

Use this when you need to:

- Send formatted text, files, or rich widgets to a user session.
- Create webhook contracts (including ephemeral/TTL) for external integrations.
- Escalate a customer conversation to a human operator.
- Understand which messaging surface to use for a given task.

## Canonical fields

### MCP messaging tools

| Tool                        | Purpose                                  | Key params                                   |
| --------------------------- | ---------------------------------------- | -------------------------------------------- |
| `teleclaude__send_result`   | Send markdown/html as a separate message | `session_id`, `content`, `output_format`     |
| `teleclaude__send_file`     | Send a file for download                 | `session_id`, `file_path`, `caption`         |
| `teleclaude__render_widget` | Render rich UI (forms, tables, actions)  | `session_id`, `data`                         |
| `teleclaude__escalate`      | Escalate customer to human admin         | `customer_name`, `reason`, `context_summary` |
| `teleclaude__publish`       | Publish to internal Redis channel        | `channel`, `payload`                         |

### Hook contract API (FastAPI on Unix socket)

Base URL: `http://localhost` via `/tmp/teleclaude-api.sock`

**List active contracts:**

```bash
curl -s --unix-socket /tmp/teleclaude-api.sock \
  "http://localhost/hooks/contracts"
```

Filter by property:

```bash
curl -s --unix-socket /tmp/teleclaude-api.sock \
  "http://localhost/hooks/contracts?property=session_id&value=abc-123"
```

**Create a contract (permanent):**

```bash
curl -s --unix-socket /tmp/teleclaude-api.sock \
  -X POST "http://localhost/hooks/contracts" \
  -H 'Content-Type: application/json' \
  -d '{
    "id": "onboard-mo",
    "target": {"url": "https://example.com/webhook"},
    "source_criterion": {"exact": "teleclaude"},
    "type_criterion": {"exact": "session_start"},
    "properties": {
      "session_id": {"exact": "abc-123"}
    }
  }'
```

**Create an ephemeral contract (TTL):**

```bash
curl -s --unix-socket /tmp/teleclaude-api.sock \
  -X POST "http://localhost/hooks/contracts" \
  -H 'Content-Type: application/json' \
  -d '{
    "id": "invite-link-xyz",
    "target": {"handler": "onboarding_handler"},
    "type_criterion": {"exact": "session_start"},
    "ttl_seconds": 180
  }'
```

The contract auto-expires after 180 seconds. Expired contracts are excluded from matching and swept every 60 seconds.

**Deactivate a contract:**

```bash
curl -s --unix-socket /tmp/teleclaude-api.sock \
  -X DELETE "http://localhost/hooks/contracts/onboard-mo"
```

**List property vocabulary:**

```bash
curl -s --unix-socket /tmp/teleclaude-api.sock \
  "http://localhost/hooks/properties"
```

### Contract fields

| Field              | Type   | Required  | Description                                                     |
| ------------------ | ------ | --------- | --------------------------------------------------------------- |
| `id`               | string | yes       | Unique contract identifier                                      |
| `target`           | object | yes       | Exactly one of `handler` (internal) or `url` (external webhook) |
| `source_criterion` | object | no        | Match event source (`exact`, `prefix`, `regex`)                 |
| `type_criterion`   | object | no        | Match event type                                                |
| `properties`       | object | no        | Match event properties (key-value criteria)                     |
| `ttl_seconds`      | int    | no        | Time-to-live; `null` = permanent                                |
| `expires_at`       | string | read-only | ISO 8601 UTC expiry (computed from `ttl_seconds`)               |
| `active`           | bool   | read-only | Whether the contract is active                                  |
| `source`           | string | read-only | Origin: `config`, `api`, `programmatic`                         |

## Allowed values

Target types:

- `handler`: internal Python callable name (e.g., `"onboarding_handler"`)
- `url`: external HTTPS webhook URL (delivery uses HMAC-SHA256 signing)

Criterion operators (for `source_criterion`, `type_criterion`, property values):

- `exact`: exact string match
- `prefix`: prefix match
- `regex`: regular expression match

TTL behavior:

- `ttl_seconds > 0`: contract expires after N seconds
- `ttl_seconds = null` or omitted: contract never expires
- `ttl_seconds <= 0`: rejected with HTTP 422

## Known caveats

- Expired contracts are excluded from matching immediately but only deactivated in the database every 60 seconds by the sweep loop.
- `send_result` and `send_file` require a valid `session_id` from `TMPDIR/teleclaude_session_id`.
- `render_widget` renders differently per adapter: rich interactive UI on web, text summary on Telegram, plain text in terminal.
- `escalate` is only available in customer sessions (Discord help desk flow).
- Hook contract delivery to external URLs uses HMAC-SHA256 with the contract's `secret` field for authentication.
- The hook API is on the internal Unix socket only; it is not exposed publicly.
