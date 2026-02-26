---
id: 'project/procedure/deploy'
type: 'procedure'
scope: 'project'
description: 'How TeleClaude updates propagate to computers via the automated deployment pipeline.'
---

# Deploy — Procedure

## Goal

Understand how code updates reach TeleClaude computers via the automated
webhook-driven deployment pipeline.

## Overview

Deployment is fully automated. Computers subscribe to GitHub events
(push to main, release published) and self-update based on their configured
deployment channel. No manual `telec deploy` command is needed.

## Deployment Channels

Each computer declares a channel in `config.yml`:

| Channel  | Trigger                            | Notes                             |
| -------- | ---------------------------------- | --------------------------------- |
| `alpha`  | Every push to `main`               | Latest code, may be unstable      |
| `beta`   | GitHub release published           | Tagged releases only              |
| `stable` | Release within pinned minor series | Requires `pinned_minor` in config |

## How It Works

1. A GitHub webhook fires on push or release event.
2. The daemon's webhook handler evaluates the event against the computer's channel config.
3. If the event matches, `execute_update` runs: `git pull --ff-only`, migrations, daemon restart.
4. For `alpha` and `beta`, the daemon also publishes a fan-out event to Redis
   (`deployment:version_available`) so remote computers on the same channel also update.

## Monitoring

After a push or release, verify computers updated via `make status` or by
checking the daemon version: `telec version`.

## Recovery

If auto-update fails on a computer, fall back to SSH:

```bash
ssh -A {user}@{host} 'cd <teleclaude-path> && git pull --ff-only origin main && make restart && make status'
```

(See `config.yml` for computer list, host names, and teleclaude paths.)

## Outputs

- Automatic daemon restart with updated code on all subscribed computers.

## See Also

- `docs/project/design/architecture/deployment-pipeline.md` — full architecture
- `docs/project/spec/teleclaude-config.md` — deployment channel configuration
