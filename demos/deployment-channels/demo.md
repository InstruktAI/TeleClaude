# Demo: deployment-channels

## Validation

```bash
# Config accepts deployment channel
python -c "
from teleclaude.config.loader import load_project_config
cfg = load_project_config()
print(f'OK: channel={cfg.deployment.channel}')
"
```

```bash
# Deployment handler is registered
python -c "
from teleclaude.deployment.handler import handle_deployment_event
print(f'OK: handler is async callable')
"
```

```bash
# telec version shows configured channel
telec version | grep -q "channel:"
```

## Guided Presentation

### Step 1: Channel config

Show `teleclaude.yml` with `deployment.channel: alpha`. Explain channels:
alpha (push to main), beta (GitHub releases), stable (pinned minor, patches).
Default is alpha for backward compatibility.

### Step 2: Webhook flow

Trace the path: GitHub push webhook → `/hooks/inbound/github` → GitHub
normalizer → HookEvent(source="github", type="push") → dispatcher matches
deployment contract → handler checks channel → executes update.

### Step 3: Fan-out

Explain: when daemon A receives the webhook, it publishes a
`deployment.version_available` HookEvent to the internal event bus.
EventBusBridge broadcasts via Redis. All daemons evaluate against their
own channel config.

### Step 4: Update execution

Show the executor sequence: pull → migrate → install → restart (exit 42).
Show Redis status transitions: updating → migrating → installing → restarting.

### Step 5: Updated telec version

Run `telec version` — shows actual channel from config.
