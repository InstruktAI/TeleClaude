# Event Envelope Schema — Input

## Context

The event envelope is the universal format for all communication in the TeleClaude
mesh. Every event — local notifications, peer-to-peer messages, service publications,
governance signals — uses the same envelope. The wire format is JSON. Telec is the
shared codec. Schema versioning IS telec versioning.

## The Five Layers

Every envelope has five conceptual layers:

### 1. Identity: Who am I

Fixed properties, always present:

- `event` — dotted type (e.g., `service.published`, `todo.created`)
- `version` — schema version (= telec version)
- `source` — node identity (cryptographic)
- `timestamp` — ISO 8601
- `idempotency_key` — deduplication key

### 2. Semantic: How to make sense of me

- `level` — event level (0: infrastructure, 1: operational, 2: workflow, 3: business)
- `domain` — the domain this event belongs to
- `entity` — reference URI (e.g., `telec://deployment/abc`)
- `description` — human/AI-readable natural language description of what happened

### 3. Data: What happened

- `payload` — freeform object. The actual event data. Structure varies by event type.

### 4. Affordances: What can you do with me

- `actions` — map of named actions, each with:
  - `description` — what this action does
  - `produces` — what event type this action would emit
  - `outcome_shape` — expected success/failure event types

Affordances are DESCRIPTIVE, never instructive. They describe possibilities. The
receiving AI decides whether to act based on its own sovereignty rules.

### 5. Resolution: What "done" looks like

- `terminal_when` — condition for this event to be considered resolved
- `resolution_shape` — expected shape of the resolution payload

## Core Event Taxonomy

Root-level event families (the fixed nouns):

- `service.*` — service lifecycle (published, updated, deprecated, removed)
- `node.*` — node lifecycle (alive, leaving, descriptor_updated)
- `todo.*` — work items (created, dumped, activated, completed)
- `deployment.*` — deploy lifecycle (started, completed, failed, rolled_back)
- `content.*` — content lifecycle (dumped, refined, published)
- `notification.*` — meta-events (escalation, resolution)
- `schema.*` — schema evolution (proposed, adopted)
- `pr.*` — pull request lifecycle (created, voted, merged, closed)

## Additional Properties: The Expansion Joint

The schema allows additional properties at every level. No validation on unknowns.
AIs interpret them best-effort. This is the mechanism for organic evolution:

1. A node's AI encounters a situation the schema doesn't cover
2. It uses additional properties to express what it needs
3. Other nodes' AIs interpret the additional properties intelligently
4. If the property proves useful across the mesh (not a one-off), the originating
   AI or any AI that notices the pattern creates a PR to add it to the formal schema
5. Community votes (AI reactions + human review). Merge or close.
6. Merged changes ship via normal git release channels
7. All nodes update. The additional property is now a formal field. Strict mode.

This cycle is self-cleaning: additional properties accumulate as noise, useful ones
get promoted to formal schema via PRs, noise drops because validated fields are
handled natively. Entropy decreases through governance.

## Schema Versioning

Schema versioning IS telec versioning. When TeleClaude ships v2.1, the schema is v2.1.
Backward compatibility: nodes on v2.0 ignore fields they don't recognize. Nodes on v2.1
handle them natively. Additional properties are always forward-compatible.

Schema evolution proposals travel through the mesh as awareness (`schema.proposed`
events). Schema adoption travels through GitHub (PR, review, merge, release). These
are two different channels with two different trust levels. The mesh is open. GitHub
is governed. That separation is the security boundary for schema integrity.

## Example Envelope

```yaml
# === Identity ===
event: deployment.failed
version: 1
source: node-abc-123
timestamp: 2026-02-28T10:00:00Z
idempotency_key: 'deploy:instrukt-proxy:v2.4.1:attempt-3'

# === Semantic ===
level: 3
domain: infrastructure
entity: 'telec://deployment/abc'
description: >
  Deployment of instrukt-proxy v2.4.1 to staging failed
  on attempt 3 of 3. Container health check timed out.

# === Data ===
payload:
  service: instrukt-proxy
  version: v2.4.1
  target: staging
  attempt: 3
  error: health_check_timeout

# === Affordances ===
actions:
  retry:
    description: Retry the deployment with same config
    produces: deployment.started
    outcome_shape:
      success: deployment.completed
      failure: deployment.failed
  escalate:
    description: Escalate to human operator
    produces: notification.escalation
  rollback:
    description: Roll back to previous stable version
    produces: deployment.started

# === Resolution ===
terminal_when: 'action taken OR 3 hours elapsed'
resolution_shape:
  action_taken: string
  result: 'telec://deployment/{new_id}'
  resolved_by: string
```

## Dependencies

- event-platform (the internal processor that handles envelopes)
- mesh-architecture (the transport that carries envelopes between nodes)
