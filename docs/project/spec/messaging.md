---
id: 'project/spec/messaging'
type: 'spec'
scope: 'project'
description: 'Messaging tools for Telegram, Discord, and email delivery — hooks, files, widgets, and escalation.'
---

# Messaging — Spec

## What it is

TeleClaude exposes several messaging tools for agents to deliver content to users and external systems. These flows operate through the daemon's Unix socket API (`/tmp/teleclaude-api.sock`) and the `telec` CLI command surface.

Use this when you need to:

- Send formatted text, files, or rich widgets to a user session.
- Create webhook contracts (including ephemeral/TTL) for external integrations.
- Escalate a customer conversation to a human operator.
- Understand which messaging surface to use for a given task.

## Canonical fields

### Messaging command surface

| Command                   | Purpose                                  | Key params                             |
| ------------------------- | ---------------------------------------- | -------------------------------------- |
| `telec sessions result`   | Send markdown/html as a separate message | `session_id`, `content`, `--format`    |
| `telec sessions file`     | Send a file for download                 | `session_id`, `--path`, `--caption`    |
| `telec sessions widget`   | Render rich UI (forms, tables, actions)  | `session_id`, `--data`                 |
| `telec sessions escalate` | Escalate customer to human admin         | `session_id`, `--customer`, `--reason` |
| `telec channels publish`  | Publish to internal Redis channel        | `channel`, `--data`                    |

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

### Transcript normalization (outbound rendering)

Before adapter rendering, transcript entries are normalized into a canonical assistant/user message shape:

- `role`: `user` or `assistant`
- `content[]` block types:
  - `text` / `output_text` for user-visible assistant text
  - `thinking` for model reasoning/thought text
  - `tool_use` / `tool_result` for tool activity

Source mapping is agent-specific but canonical at render time:

- Claude: native `thinking` blocks map directly.
- Gemini: `thoughts[].description` maps to `thinking`.
- Codex: `response_item.payload.type == "reasoning"` maps to `thinking`.

Adapter policy:

- Telegram/Discord/terminal-oriented threaded output renders `thinking` in italics.
- Web UI may render `thinking` as a dedicated toggle/collapsible reasoning part.
- Core owns normalization; adapters own presentation.
- Session message APIs expose canonical block types (`text`, `thinking`, `tool_use`, `tool_result`) without server-side filtering; clients/adapters decide what to render.

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
