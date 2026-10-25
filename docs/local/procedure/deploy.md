---
description: 'How TeleClaude updates propagate to computers: one public ingress terminates external webhooks and relays them to the cluster, and every installation converges by the channel it follows — edge to green main revisions, stable to releases — reading its source directly where no relay reaches it.'
visibility: 'public'
---

# Deploy — Procedure

## Goal

Understand how code updates reach TeleClaude installations under the
single-ingress + reconciliation model: one computer terminates external
webhooks for the whole cluster and relays them, and every installation keeps
itself on the newest revision its channel admits without a manual command.

## Preconditions

- Deployment is fully automated. One computer is the cluster's **ingress** —
  the single publicly reachable node for inbound webhooks. Every installation
  reacts to the relayed signals and to its own interval read of its source, and
  converges by its configured channel. No manual deploy command is needed.

## Steps

### Deployment channels

Each installation follows the repository it was installed from — upstream or a
fork — on a channel declared in `config.yml`:

| Channel  | Converges to                                                        | Notes                                                                             |
| -------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `edge`   | The newest main revision every required check has passed            | Never a red or unchecked revision                                                 |
| `stable` | Published releases within the active release's compatibility series | A release beyond the series is held and carried out by the installation inspector |

The declaration and its default are owned by
`local/projects/teleclaude/spec/feature/config/stable-channel-pinning-rule`, and
what each channel admits by
`local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update`.

### The ingress terminates external webhooks for the cluster

One computer is the ingress. It need not be the master — a cheap always-on
appliance (e.g. a Raspberry Pi) is ideal. It is the only node exposed to the
internet:

1. The ingress serves its inbound endpoints over plain HTTP on loopback only.
   A reverse proxy on the same computer is the public surface: it terminates
   TLS and forwards the inbound path prefix to the ingress. Any local reverse
   proxy works.
2. An external provider (GitHub releases, workflow runs, provider webhooks)
   sends a webhook; it arrives only at the ingress.
3. The ingress verifies each request against the secret of the home that
   declared its source, translates it into a platform event, and relays it to
   the cluster **unconditionally** — regardless of its own channel or whether
   it would itself act. The ingress decides nothing about the reaction.

No other computer accepts external webhooks; the cluster's single public
surface is the ingress alone.

### Every installation converges by its channel

Each installation's running daemon reacts to its source's relayed green
announcements
(`local/projects/teleclaude/spec/feature/integration/ci-run-outcomes`) and
published releases, and reads its source on a fixed interval, so a machine
outside the cluster — another person's computer — converges as well. On a match
it installs the target through the install act exactly once
(`local/projects/teleclaude/spec/feature/reconciliation/installed-releases`).
A release beyond a stable installation's compatibility series is held and its
upgrade is carried out by the installation inspector on that computer
(`sdlc/procedure/maintenance/installation/overview`). A computer behind a
home router stays private and still updates.

### Operator setup (ingress only, one-time)

- Flag the ingress computer as the ingress node in its machine configuration.
- Route the inbound path prefix of the public webhook host from the local
  reverse proxy to the ingress's loopback listener.
- Declare the GitHub source in the receiving project's `teleclaude.yml`, with
  its secret as a reference resolved from that project's `.env`, on the ingress
  computer (`local/projects/teleclaude/spec/feature/integration/inbound-webhook-endpoint-framework`).

- Register the project's endpoint URL and the same secret at the provider, and
  subscribe TeleClaude's repository webhook to its push, release and workflow
  run events. Workflow runs carry its CI results
  (`local/projects/teleclaude/spec/feature/integration/ci-run-outcomes`).
- For a project that declares its repository and App (`todos.repository`,
  `todos.app`), grant that App read access to the repository's Actions and
  contents. The platform publishes that project's CI run outcomes, and needs the
  access to name a failed run's jobs and steps and the commits since the last
  green run.

### Monitoring

After a green revision or a release, verify installations updated with
`telec app status` on each computer: it names the active release, the channel,
the most recent convergence decision and any held release.

## Outputs

- Each installation converges to the newest revision its channel admits,
  restarting healthy — without operator action — and a breaking release is
  carried out by its installation inspector.
- Only the ingress is publicly exposed; every other computer reacts privately
  through the cluster or its own interval read.

## Recovery

If an installation did not update, run `telec app status` on that computer: the
convergence decision names why — no newer green revision, a held release, or a
failed install with the stores it changed — and a failed install is recovered
under `local/projects/teleclaude/spec/feature/reconciliation/installed-releases`.

If an installation cannot converge by itself, install a revision on that one
machine over SSH:

```bash
ssh -A {user}@{host} 'telec app install <revision> && telec app status'
```

(See `telec computers list` for the computer list and host names.)

If the ingress itself is down, the cluster processes no external events but is
not otherwise broken; every installation still converges through its interval
read of its source. The relay is stateless, so a second ingress can be added
without redesign.

## See Also

- docs/local/design/architecture/deployment-pipeline.md — pipeline architecture
- docs/local/spec/feature/integration/single-ingress-webhook-termination.md — ingress contract
- docs/local/spec/feature/reconciliation/channel-gated-self-update.md — self-update contract
- docs/local/spec/domain/reconciliation.md — reconciliation bounded context
- docs/local/adr/0028-single-lan-bound-ingress.md
- docs/local/adr/0111-external-events-enter-as-ordinary-platform-events.md
- docs/local/adr/0024-reconciliation-bounded-context.md
- docs/local/spec/teleclaude-config.md — deployment channel configuration
