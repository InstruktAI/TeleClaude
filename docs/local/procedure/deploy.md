---
description: 'How TeleClaude updates propagate to computers: one public ingress terminates external webhooks and relays them to the cluster, where every computer self-updates by its channel.'
visibility: 'public'
---

# Deploy — Procedure

## Goal

Understand how code updates reach TeleClaude computers under the
single-ingress + reconciliation model: one computer terminates external
webhooks for the whole cluster and relays them, and every computer keeps
itself on the newest release for its channel without a manual command.

## Preconditions

- Deployment is fully automated. One computer is the cluster's **ingress** —
  the single publicly reachable node for inbound webhooks. Every other
  computer reacts by subscription and self-updates based on its configured
  deployment channel. No manual `telec deploy` command is needed.

## Steps

### Deployment channels

Each computer declares a channel in `config.yml`:

| Channel  | Trigger                                 | Notes                                    |
| -------- | --------------------------------------- | ---------------------------------------- |
| `alpha`  | Every push to `main`                    | Latest code, may be unstable             |
| `beta`   | GitHub release published                | Tagged releases only                     |
| `stable` | Release within its compatibility series | Requires a declared compatibility series |

The stable series declaration is owned by
`local/projects/teleclaude/spec/feature/config/stable-channel-pinning-rule`, and
which releases a series admits by
`local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update`.

### The ingress terminates external webhooks for the cluster

One computer is the ingress. It need not be the master — a cheap always-on
appliance (e.g. a Raspberry Pi) is ideal. It is the only node exposed to the
internet:

1. The ingress serves its inbound endpoints over plain HTTP on loopback only.
   A reverse proxy on the same computer is the public surface: it terminates
   TLS and forwards the inbound path prefix to the ingress. Any local reverse
   proxy works.
2. An external provider (GitHub releases, provider webhooks) sends a webhook;
   it arrives only at the ingress.
3. The ingress verifies each request against the secret of the home that
   declared its source, translates it into a platform event, and relays it to
   the cluster **unconditionally** — regardless of its own channel or whether
   it would itself act. The ingress decides nothing about the reaction.

No other computer accepts external webhooks; the cluster's single public
surface is the ingress alone.

### Every computer self-updates by its channel

TeleClaude's own checkpoint overlay binds the relayed pushes and releases of its
repository to its `self-update` maintenance action
(`local/projects/teleclaude/spec/feature/integration/event-bound-maintenance`).
Every computer whose TeleClaude checkout is its canonical checkout on the main
branch performs that action on its own checkout. The action evaluates the event
against the computer's channel policy and, on a match, advances main to that
version **exactly once**; the maintenance that advance owes installs and
restarts the computer onto the new version. A computer behind a home router
stays private and still updates, because the event reaches it over the cluster
bus, not a public endpoint.

### Operator setup (ingress only, one-time)

- Flag the ingress computer as the ingress node in its machine configuration.
- Route the inbound path prefix of the public webhook host from the local
  reverse proxy to the ingress's loopback listener.
- Declare the GitHub source in the receiving project's `teleclaude.yml`, with
  its secret as a reference resolved from that project's `.env`, on the ingress
  computer (`local/projects/teleclaude/spec/feature/integration/inbound-webhook-endpoint-framework`).

- Register the project's endpoint URL and the same secret at the provider, and
  subscribe TeleClaude's repository webhook to its push and release events.

### Monitoring

After a push or release, verify computers updated via `make status` or by
checking the daemon version: `telec version`.

## Outputs

- Each subscribed computer converges to the newest version its channel admits,
  restarting healthy — without operator action.
- Only the ingress is publicly exposed; every other computer reacts privately
  through the cluster.

## Recovery

If a computer received the event but did not update, run
`telec code maintenance status` in its TeleClaude checkout: a failed
`self-update`, or a failed step of the maintenance its advance owes, is listed
with the replay that recovers it once its cause is fixed.

If a computer fails to auto-update, fall back to SSH for that one machine:

```bash
ssh -A {user}@{host} 'cd <teleclaude-path> && git pull --ff-only origin main && make restart && make status'
```

(See `config.yml` for computer list, host names, and teleclaude paths.)

If the ingress itself is down, the cluster processes no external events but is
not otherwise broken; it recovers on the next release signal (or a periodic
self-check). The relay is stateless, so a second ingress can be added without
redesign.

## See Also

- docs/local/design/architecture/deployment-pipeline.md — pipeline architecture
- docs/local/spec/feature/integration/single-ingress-webhook-termination.md — ingress contract
- docs/local/spec/feature/reconciliation/channel-gated-self-update.md — self-update contract
- docs/local/spec/domain/reconciliation.md — reconciliation bounded context
- docs/local/adr/0028-single-lan-bound-ingress.md
- docs/local/adr/0111-external-events-enter-as-ordinary-platform-events.md
- docs/local/adr/0024-reconciliation-bounded-context.md
- docs/local/spec/teleclaude-config.md — deployment channel configuration
