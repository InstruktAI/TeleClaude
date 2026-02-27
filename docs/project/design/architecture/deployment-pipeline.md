---
id: 'project/design/architecture/deployment-pipeline'
type: 'design'
scope: 'project'
description: 'Architecture of the automated webhook-driven deployment pipeline.'
---

# Deployment Pipeline — Design

## Overview

TeleClaude uses an automated webhook-driven deployment pipeline. When code is
pushed to `main` or a GitHub release is published, computers self-update based
on their configured deployment channel. No manual operator command is needed.

## Components

### `teleclaude/deployment/handler.py`

Receives webhook events from GitHub (push, release). Evaluates the event
against the computer's channel configuration and triggers an update if the
event matches.

**Decision matrix:**

| Event                       | Channel  | Condition                         | Action |
| --------------------------- | -------- | --------------------------------- | ------ |
| Push to `main`              | `alpha`  | Always                            | Update |
| Release published           | `beta`   | Any version                       | Update |
| Release published           | `stable` | Within `pinned_minor` series      | Update |
| Fan-out `version_available` | any      | Own channel matches event channel | Update |

### `teleclaude/deployment/executor.py`

Runs the actual update: `git pull --ff-only`, migration runner, daemon restart.

### `teleclaude/deployment/migration_runner.py`

Discovers and runs sequential migration scripts between versions.

### Redis Fan-out

When a GitHub-source event triggers an update on the receiving computer, that
computer also publishes a `version_available` event to the Redis stream
`deployment:version_available`. All other daemons subscribed to the stream
evaluate the event and update if their channel config matches.

This means only one computer needs a direct GitHub webhook connection. Others
receive updates via Redis fan-out.

## Deployment Channels

Configured in `project.deployment.channel` in `config.yml`:

```yaml
project:
  deployment:
    channel: alpha # alpha | beta | stable
    pinned_minor: '1.2' # required when channel=stable
```

## Flow Diagram

```
GitHub → Webhook → handler.py
                     ↓
              channel match?
                ↙         ↘
             yes             no → skip
              ↓
          executor.py
        (git pull + restart)
              ↓
        Redis fan-out
       version_available
              ↓
       Other daemons
    (evaluate own channel)
```

## Error Handling

- Config load failure: logged, update skipped (non-fatal).
- `execute_update` failure: logged via task exception handler.
- Fan-out loop prevention: events with `source=deployment` do not re-broadcast.

## See Also

- `docs/project/procedure/deploy.md` — operator procedure
- `docs/project/spec/teleclaude-config.md` — config schema for deployment
