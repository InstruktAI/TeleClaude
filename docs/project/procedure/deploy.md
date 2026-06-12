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

| Channel  | Trigger                            | Notes                             |
| -------- | ---------------------------------- | --------------------------------- |
| `alpha`  | Every push to `main`               | Latest code, may be unstable      |
| `beta`   | GitHub release published           | Tagged releases only              |
| `stable` | Release within pinned minor series | Requires `pinned_minor` in config |

### The ingress terminates external webhooks for the cluster

One computer is the ingress. It need not be the master — a cheap always-on
appliance (e.g. a Raspberry Pi) is ideal. It is the only node exposed to the
internet:

1. The ingress webhook server binds to the machine's LAN/router address. The
   router port-forwards public inbound traffic to it, and accepted sources are
   restricted to the router — reachable for legitimate forwarded traffic
   without being promiscuously open.
2. An external provider (GitHub releases, provider webhooks) sends a webhook;
   it arrives only at the ingress.
3. The ingress verifies each payload (per-provider signature), normalizes it
   into the unified event shape, and relays it onto the cluster event bus
   **unconditionally** — regardless of its own channel or whether it would
   itself act. The ingress decides nothing about the reaction.

No other computer accepts external webhooks; the cluster's single public
surface is the ingress alone.

### Every computer self-updates by its channel

Each computer subscribes to the relayed cluster event and reacts according to
its own configuration. When the event is a release/version signal, the
computer evaluates it against its channel policy and, on a match, converges to
that version: it applies the target **exactly once** and returns to a healthy
running state on the new version. A computer behind a home router stays
private and still updates, because the signal reaches it over the cluster bus,
not a public endpoint.

### Operator setup (ingress only, one-time)

- Port-forward the provider's public webhook traffic at the router to the
  ingress's LAN bind address.
- Configure the shared webhook secret used for signature verification.
- Register the public webhook URL at the provider (e.g. GitHub).

### Monitoring

After a push or release, verify computers updated via `make status` or by
checking the daemon version: `telec version`.

## Outputs

- Each subscribed computer converges to the newest version its channel admits,
  restarting healthy — without operator action.
- Only the ingress is publicly exposed; every other computer reacts privately
  through the cluster.

## Recovery

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

- docs/project/design/architecture/deployment-pipeline.md — pipeline architecture
- docs/project/spec/feature/integration/single-ingress-webhook-termination.md — ingress contract
- docs/project/spec/feature/reconciliation/channel-gated-self-update.md — self-update contract
- docs/project/spec/domain/reconciliation.md — reconciliation bounded context
- docs/project/adr/0028-single-lan-bound-ingress.md
- docs/project/adr/0024-reconciliation-bounded-context.md
- docs/project/spec/teleclaude-config.md — deployment channel configuration
