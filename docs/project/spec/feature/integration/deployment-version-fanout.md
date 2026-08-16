---
description: 'Superseded v1 mechanism. A deployment-only cross-host fan-out of version-available signals with self-skip on origin. The durable, version-agnostic posture — single-ingress relay plus per-node channel-gated convergence — is owned by single-ingress-webhook-termination and channel-gated-self-update.'
visibility: 'public'
---

# Deployment Version Fanout — Spec

## What it is

**Status: not the current mechanism.** This spec describes the v1 deployment-only
fan-out. The current deployment contracts are single-ingress webhook termination
(`@docs/project/spec/feature/integration/single-ingress-webhook-termination.md`)
for the inbound boundary — one ingress verifies, normalizes, and relays each
event to the cluster unconditionally — and channel-gated self-update
(`@docs/project/spec/feature/reconciliation/channel-gated-self-update.md`) for the
per-node reaction, where each node evaluates the relayed signal against its
channel policy and converges exactly once. The scenarios below are not a binding
target.

The v1 mechanism: a long-running cross-host consumer on each integration service that
reads from the deployment fanout channel and dispatches each message as
a local hook event through the integration service's own hook
dispatcher. This fans out a deployment version-available signal to all
integration services in the cluster: when one service receives a GitHub
release webhook (or otherwise detects a new version), it publishes a
deployment / version-available event onto the cross-host channel; every
other service reads it and runs its local update flow.

Self-origination is detected via a host identifier carried in the event
payload; a service skips messages whose host identifier matches its own
configured computer name to avoid re-executing an update it scheduled
directly from the GitHub-source path. The originating service publishes
the fanout **before** scheduling its local update task (publish is
awaited; the local update runs in the background), so remote services
can begin their update in parallel with the local one.

## Canonical fields

### Use cases

#### UC-DF1: Remote service receives the fanout and runs the update

```gherkin
Given service A on host "alpha" received a GitHub release webhook and entered the deployment-event handler with an update required
And A awaits the fanout publish, which writes a hook event (source="deployment", type="version_available", host identifier="alpha") onto the cross-host channel
And only AFTER the publish returns, A schedules its own local update task in the background
When service B on host "beta" reads the channel
Then it decodes the event payload
And reconstructs the hook event
And detects host identifier == "alpha" != its own configured computer name ("beta")
And calls the local hook dispatcher with the event
And the dispatcher matches the built-in deployment-fanout contract
And the deployment-event handler runs on service B (event source is "deployment", so no second fanout is published — only github-source events publish)
And the handler on B schedules its own local update task

The originating service's publish-before-execute ordering means: when
the publish fails, remote services miss the fanout but A still proceeds
with its local update; when the local update fails, the fanout has
already gone out to other services.
```

#### UC-DF2: Self-skip to avoid double execution

```gherkin
Given service A reads its own message from the channel
When the consumer evaluates the host identifier against its configured computer name
Then it logs "deployment fanout: skipping self-originated message" at debug
And does NOT dispatch — the GitHub-source path is the same deployment-event handler call that awaited the publish and then scheduled the local update task after the publish returned
```

#### UC-DF3: Cursor starts at "now" — only new messages

```gherkin
Given the service starts up
When the fanout consumer initializes
Then its cursor is positioned at "now" so reads only return messages published AFTER startup
And no historical messages are replayed on service restart
```

#### UC-DF4: Decoding tolerance for raw and decoded payloads

```gherkin
Given the channel client may return data values in raw or decoded form
When the consumer reads the event field
Then it tries both encodings
And decodes raw bytes before reconstructing the hook event
```

#### UC-DF5: Dispatch failure is logged and consumption continues

```gherkin
Given an event payload fails to parse or the dispatcher raises
When the consumer catches the exception
Then a warning "deployment fanout: dispatch failed" is logged with the exception
And the consumer continues with the next message (does NOT halt)
And the cursor is still advanced (the failed message is not retried)
```

#### UC-DF6: Connectivity error backoff

```gherkin
Given the consumer encounters a connectivity error against the cross-host channel
When the outer guard catches the exception
Then a warning "deployment fanout consumer error" is logged
And the consumer waits briefly before retrying
And loops back to re-establish the connection
```

#### UC-DF7: Shutdown via cancellation

```gherkin
Given the service's shutdown is initiated OR the consumer task is cancelled
When the cancellation surfaces inside the read
Then the consumer loop exits cleanly
And "deployment fanout consumer stopped" is logged
```

### Cross-context references

- Cluster-scoped delivery — every integration service in the
  deployment runs its own consumer. The mechanism is the v1
  expression of the v2 domain spec's cluster-visibility posture for
  cross-context events.
- Initial trigger sources include `github-webhook-normalization`
  (push / release events) and any other path that emits a
  deployment / version-available event through the local dispatcher.
- The consumer dispatches through `eventbus-hook-bridge`'s dispatcher
  (sharing the contract matcher and handler registry).
- The deployment update handler lives outside `integration`
  (in the deployment subsystem); this snippet documents the
  integration-side transport, not the deployment business logic.

## Known caveats

- The cross-host channel uses an append-only stream with a per-consumer
  cursor. Crash recovery starts from "now" — meaning unread messages
  published while the service was down are NOT replayed. This is a
  deliberate simplification: the GitHub-source service retries publish
  on its own cadence, and the deployment system has eventual-consistency
  guarantees that tolerate skipped fanouts.
- The read blocks for a bounded interval to keep the loop responsive to
  shutdown signals.
- Self-skip relies on the publishing service's host identifier matching
  the configured computer name on the consuming service — naming drift
  between publisher and local config would defeat the self-skip and
  could re-execute updates.
- The consumer does NOT dedupe across messages; if the same version
  message is published twice with different host identifiers, both
  remote services would dispatch (and the deployment handler must be
  idempotent to absorb).
- This is the only cross-host channel dispatch path in v1 integration;
  all other event flows are local hook outbox or in-process event bus.
- Per-message backpressure is bounded only by the read batch size; under
  high publish rates the consumer can fall behind without observable
  signal beyond delayed dispatch.

## See Also

- docs/project/spec/feature/integration/single-ingress-webhook-termination.md
- docs/project/spec/feature/reconciliation/channel-gated-self-update.md
- docs/project/adr/0028-single-lan-bound-ingress.md
- docs/project/adr/0024-reconciliation-bounded-context.md
