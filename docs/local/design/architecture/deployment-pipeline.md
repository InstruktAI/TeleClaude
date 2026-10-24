---
description: 'Architecture of the deployment pipeline: a single ingress terminates external webhooks and relays them to the cluster bus, where each computer reconciles its own version by channel.'
visibility: 'public'
---

# Deployment Pipeline — Design

## Purpose

TeleClaude keeps a multi-machine fleet current automatically. The pipeline has
two responsibilities, owned by two bounded contexts on different change axes:

- **Ingress (`integration`)** — terminate external webhooks for the whole
  cluster at one public node, verify and normalize each payload, and relay it
  onto the cluster event bus unconditionally.
- **Convergence (`reconciliation`)** — every computer holding TeleClaude's
  canonical checkout reacts to the relayed pushes and releases of TeleClaude's
  own repository and drives its own actual state toward its desired state: the
  newest version its channel admits, applied exactly once, ending healthy.

The ingress decides nothing about the reaction; the reaction is
subscriber-driven. This separation is the recorded decision in ADR-0028
(single-ingress termination) and ADR-0024 (reconciliation as its own bounded
context); ADR-0055 supersedes ADR-0028's bind topology with proxy-fronted reuse
of the localhost API server.

### Ingress — `teleclaude/hooks/inbound.py`

The ingress serves the inbound endpoints on loopback only, behind a mandatory
same-host reverse proxy that terminates TLS, restricts source, and forwards only
the inbound path prefix. A project receives GitHub deliveries by declaring a
GitHub source in its own configuration; the ingress verifies each delivery
against that project's secret, translates it, and relays it. Webhook routes
authenticate by signature alone and inherit no loopback identity-trust. One
ingress terminates requests for every provider and every home. See
`docs/local/spec/feature/integration/single-ingress-webhook-termination.md` and
`docs/local/spec/feature/integration/inbound-webhook-endpoint-framework.md`.

### Cluster relay

A verified delivery is published on the platform event stream at cluster scope
as the platform event `github.<event>`, emitted on the ingress, with the
declaring project as its origin. Every computer reads the stream through its own
consumers. Only the ingress is publicly exposed. The relay is stateless, so a
second ingress can be added without redesign.

### Convergence — `reconciliation`

TeleClaude's own checkpoint overlay binds `github.push` and `github.release` to
its `self-update` maintenance action. On every computer holding TeleClaude's
canonical checkout, such an event whose origin is TeleClaude becomes an event
activation of the commit-boundary executor
(`docs/local/spec/feature/integration/event-bound-maintenance.md`). An event
about any other project never selects that binding.

The action reads the event it is handed and the computer's channel policy. On a
match it advances the checkout's main branch to the target the channel admits —
the newest mainline for alpha, the published release for beta and stable. A
target the checkout already contains is not applied again. The advance is an
ordinary canonical-main activation: the installation, dependency
reconciliation and daemon restart it owes are the commit-boundary maintenance
its changed paths owe
(`docs/local/spec/feature/integration/post-commit-maintenance.md`), and an
activation whose range changes the installed version also owes the
installation migrations between the version it left and the version it
reached. Those migrations run inside the activation's stopped-daemon window,
before its configuration migration run. The window verifies that the daemon
started again on the reached version; whether the runtime then behaves
correctly is the standing integrator's judgment.
Channel policy and the exactly-once / healthy-or-failed contract are owned by
`docs/local/spec/feature/reconciliation/channel-gated-self-update.md`; the
context model (Installation, Convergence Run, Fleet Capability Map) is in
`docs/local/spec/domain/reconciliation.md`.

A deliberately multi-version fleet (alpha ahead of beta ahead of stable) stays
interoperable through the fleet capability map and feature-ID gating in
`teleclaude/core/reconciliation/` — unaware nodes drop ignorable capabilities
cleanly, and removal of a shared capability waits until every live node carries
it. See
`docs/local/spec/feature/reconciliation/fleet-cross-version-interop.md`.

### Current implementation surface

The ingress (`teleclaude/hooks/inbound.py`) and the fleet capability map /
feature-ID registry (`teleclaude/core/reconciliation/`) are in place. The
convergence reaction is the `self-update` maintenance action, whose channel
evaluation, advance and migrations live in `teleclaude/deployment/`; the
standalone `reconciliation` control loop is the target owner of that reaction.
Channel configuration is the machine configuration's `deployment` block
(`docs/local/spec/teleclaude-config.md`).

### Installed and development checkout relationship

Config associates one logical project with installed and development checkout
purposes; workflow resolves their shared-state and source roots. Full installation
provisions the persistent sibling defined by
`local/projects/teleclaude/spec/feature/reconciliation/development-checkout`.
The registered relationship, rather than the clone's directory spelling, governs
every consumer. Development installation, indexing and source work operate in
that environment. The installed revision alone owns live configuration,
dependencies, services and machine-wide context activation. Development context
is separately selected under
`local/projects/teleclaude/spec/feature/context/checkout-context-selection`.

On every channel the installed checkout changes only through the convergence
above, which selects the target its channel admits. Development commits,
worktrees and integration happen in the development clone, which tracks
upstream main and holds pending docs independently. A checkout that both runs
and develops becomes the installed checkout of its association.
Migration preserves the original workflow records, live claims, worktree
ownership and unpublished source before enabling the association. A transition
that cannot preserve that work remains incomplete with its concrete recovery
condition; it does not overwrite the mixed-use checkout.

Installed revision selection consumes the release-checkout contract
(`local/projects/teleclaude/spec/feature/reconciliation/release-checkout`).

The source/deployment separation follows `sdlc/principle/design-fundamentals`
and preserves existing source work under `sdlc/policy/version-control-safety`.

### Immutable installed source

The deployment action pins the admitted immutable target for its convergence
attempt under
`local/projects/teleclaude/spec/feature/reconciliation/release-checkout`.
Channel admission retains its current policy until its own delivery changes it.
The installation's actual source is assessed against that exact target rather
than ancestry containment. Installed maintenance and publication consume the
installed source identity; alpha retains ordinary main activation. This contract
is independent of whether a development companion has been provisioned.

<!-- planned:reviewed-pr-contributions -->

### Contribution and upstream release

Public contribution is the workflow handoff in
`local/projects/teleclaude/spec/feature/workflow/contribution-export` and
`local/projects/teleclaude/spec/feature/workflow/contribution-adoption`.
Its upstream integration feeds the existing immutable release pipeline.
Contribution creation, source acceptance, release publication and local adoption
remain independently observable.
<!-- /planned:reviewed-pr-contributions -->

## Inputs/Outputs

**Inputs:**

- External provider webhooks (GitHub push to `main`, GitHub release published,
  other provider events) arriving at the single ingress.

- The machine configuration's `deployment.channel` and, for stable enrollment,
  its compatibility series.

- The relayed pushes and releases of TeleClaude's own repository, consumed by
  every computer holding its canonical checkout.

**Outputs:**

- A verified, normalized event relayed onto the cluster event bus.
- On each computer holding TeleClaude's canonical checkout whose channel admits
  the target: the checkout advanced to the target, its installation migrations
  run, and the advance's commit-boundary maintenance performed, with every
  failure recorded with its reason.

## Invariants

- **Single public surface.** Exactly one computer (the ingress) accepts
  external webhooks; every other computer reacts by subscription.
- **Unconditional relay.** The ingress relays every verified event regardless
  of its own channel, role, or whether it would itself act.
- **Only the platform's own events converge it.** Convergence starts only from
  a push or release of TeleClaude's own repository.

- **Channel-gated convergence.** A computer converges only when the event
  matches its channel policy; `stable` ignores releases outside its
  compatibility series.

- **Exactly-once per target version.** A target the checkout already contains is
  not applied again, and a replayed event performs nothing a second time.
- **Healthy-or-failed.** A convergence is complete only when the daemon is
  running and healthy on the target; a failed step is recorded with its reason
  where the standing integrator finds it and leaves the convergence incomplete
  until it is replayed, never a silent partial state.

## Primary flows

```mermaid
flowchart TD
    GH[External provider webhook] --> ING[Ingress: verify + normalize]
    ING -->|relay unconditionally| BUS[Cluster event bus CLUSTER scope]
    BUS --> N1[Computer A: event-bound maintenance]
    BUS --> N2[Computer B: event-bound maintenance]
    BUS --> N3[Computer C: event-bound maintenance]
    N1 --> O1{event about TeleClaude?}
    O1 -->|no| S0[Nothing selected]
    O1 -->|yes| P1{channel admits a target the checkout lacks?}
    P1 -->|yes| C1[self-update: advance main and record the activation]
    C1 --> W1[Stopped-daemon window: settle and stop the daemon]
    W1 --> M1[Owed maintenance: install, deps, installation migrations, configuration migration]
    M1 --> W2[Start the daemon and verify it on the reached version]
    P1 -->|no| S1[Complete without acting]
```

## Failure modes

- **Ingress down.** No external events are processed while it is down; the
  cluster is not otherwise broken. Recovery is the next release signal, a
  periodic desired-state self-check, or a second stateless ingress.
- **Unverified payload.** Signature verification fails at the ingress; nothing
  is relayed and the sender receives a rejection response.
- **A computer offline misses relayed events.** A computer that was not running
  handles the events it missed while the stream still retains them; one that
  returns after its retained window has moved on does not replay what it
  missed. Recovery is the next signal or a periodic self-check.
- **Checkout not on main.** A computer whose TeleClaude checkout is not its
  canonical checkout on the main branch performs no event-bound maintenance and
  does not converge until the checkout is back on main.
- **Convergence step failure.** A failing `self-update` keeps its event
  activation's record failed with its reason, for replay. A failing step of the
  advance's maintenance is recorded the same way in that activation, and the
  standing integrator judges the result. Config-load failure is reported as the
  action's failure.
- **Idempotent migrations.** Installation migrations are tracked; re-running
  skips already-applied steps.

## See Also

- docs/local/procedure/deploy.md — operator procedure
- docs/local/spec/feature/integration/single-ingress-webhook-termination.md
- docs/local/spec/feature/integration/event-bound-maintenance.md
- docs/local/spec/feature/reconciliation/channel-gated-self-update.md
- docs/local/spec/feature/reconciliation/fleet-cross-version-interop.md
- docs/local/spec/domain/reconciliation.md
- docs/local/adr/0028-single-lan-bound-ingress.md
- docs/local/adr/0055-proxy-fronted-ingress-reuse.md
- docs/local/adr/0111-external-events-enter-as-ordinary-platform-events.md
- docs/local/adr/0024-reconciliation-bounded-context.md
- docs/local/spec/teleclaude-config.md — config schema for deployment
