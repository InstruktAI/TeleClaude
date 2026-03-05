---
id: 'project/design/architecture/deployment-pipeline'
type: 'design'
scope: 'project'
description: 'Architecture of the automated webhook-driven deployment pipeline.'
---

# Deployment Pipeline — Design

## Purpose

TeleClaude uses an automated webhook-driven deployment pipeline. When code is
pushed to `main` or a GitHub release is published, computers self-update based
on their configured deployment channel. No manual operator command is needed.

### Components

#### `teleclaude/deployment/handler.py`

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

#### `teleclaude/deployment/executor.py`

Runs the actual update: `git pull --ff-only`, migration runner, daemon restart.

#### `teleclaude/deployment/migration_runner.py`

Discovers and runs sequential migration scripts between versions.

#### Redis Fan-out

When a GitHub-source event triggers an update on the receiving computer, that
computer also publishes a `version_available` event to the Redis stream
`deployment:version_available`. All other daemons subscribed to the stream
evaluate the event and update if their channel config matches.

This means only one computer needs a direct GitHub webhook connection. Others
receive updates via Redis fan-out.

### Deployment Channels

Configured in `project.deployment.channel` in `config.yml`:

```yaml
project:
  deployment:
    channel: alpha # alpha | beta | stable
    pinned_minor: '1.2' # required when channel=stable
```

## Inputs/Outputs

**Inputs:**

- GitHub webhook events (push to `main`, release published)
- `config.yml` with `project.deployment.channel` and optional `pinned_minor`
- Redis `version_available` stream messages from peer computers

**Outputs:**

- `git pull --ff-only` + migration run + daemon restart on matching computers
- Redis `version_available` fan-out event to notify peer computers

## Invariants

- **Channel-gated updates**: A computer only applies an update when the event matches its configured channel.
- **Single webhook receiver**: Only one computer needs a direct GitHub webhook connection; others update via Redis fan-out.
- **Fan-out loop prevention**: Events with `source=deployment` do not re-broadcast.
- **Idempotent migration runner**: Sequential migrations are tracked; re-running skips already-applied steps.

## Primary flows

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

## Failure modes

- Config load failure: logged, update skipped (non-fatal).
- `execute_update` failure: logged via task exception handler.
- Fan-out loop prevention: events with `source=deployment` do not re-broadcast.

## See Also

- docs/project/procedure/deploy.md — operator procedure
- docs/project/spec/teleclaude-config.md — config schema for deployment
