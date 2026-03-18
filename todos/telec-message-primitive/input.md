# telec-message-primitive — Input

telec message — person-addressed messaging primitive

## Vision

Agents need to send messages to people without knowing or caring which channel they're on.
`telec message` is the person-addressed primitive: resolve the person from config, pick
their preferred channel (or an explicit --channel override), and dispatch through the
existing adapter infrastructure.

## Surface

```
telec message <person> <text>
telec message <person> --file <path> [--caption <text>]
telec message <person> --channel telegram|discord|whatsapp
```

Without `--channel`, resolves to the person's active notification channel from their
personal config folder.

## Two-layer person architecture (existing — no schema changes needed)

The system already has a clean two-layer split:

**Company registry** (`~/.teleclaude/teleclaude.yml` → `people[]`):
Minimal — name, email, role, proficiency. The organization's view. Used for identity,
auth, and invitation. Does NOT hold channel credentials.

**Person folder** (`~/.teleclaude/people/{name}/teleclaude.yml`):
Rich personal ecosystem — per-channel credentials, notification preferences,
subscriptions, interests. The person's own space.

Example (already live for Maurice):
```yaml
# ~/.teleclaude/people/Maurice Faber/teleclaude.yml
creds:
  telegram:
    user_id: 1285425702
    user_name: '@Moreaze'
  discord:
    user_id: '165041196605898753'
notifications:
  telegram: true
```

The bridge is the person's `name` — it links the company registry entry to the
personal folder. No new config fields needed.

## Resolution flow

1. Match `<person>` against `people[].name` in company config (fuzzy match on name,
   exact on email)
2. Look up `~/.teleclaude/people/{name}/teleclaude.yml` for channel credentials
3. Determine channel: `--channel` flag > person's `notifications` map (active: true
   channels) > system default
4. Read credential from `creds.{channel}` (user_id, user_name, etc.)
5. Dispatch through existing adapter infrastructure

## Why now

- Agents doing proactive work (reflective heartbeats, background discoveries) need to
  reach humans without being in an active session
- Current workaround (`telec sessions result`) only works within the current session's
  origin adapter — useless for out-of-band communication
- `teleclaude/entrypoints/send_telegram.py` proves the Telegram direct send path works
  end-to-end — this generalizes it across channels
- The two-layer person config with per-channel credentials already exists and is populated

## Key files

- `teleclaude/entrypoints/send_telegram.py` — existing direct Telegram send (reference pattern)
- `~/.teleclaude/teleclaude.yml` — company registry (person name resolution)
- `~/.teleclaude/people/{name}/teleclaude.yml` — personal config (channel credentials)
- `teleclaude/cli/telec/surface.py` — CLI surface (add message subcommand)
- `teleclaude/adapters/telegram/message_ops.py` — existing Telegram adapter send
- `teleclaude/adapters/discord/message_ops.py` — existing Discord adapter send

## Future use

This primitive is the foundation for agent-initiated human contact. When an agent has a
reflective heartbeat and discovers something worth sharing, it says
`telec message Maurice "I noticed something about the integration pattern"` — and the
system routes it to wherever Maurice is listening. The agent never needs to know the channel.
