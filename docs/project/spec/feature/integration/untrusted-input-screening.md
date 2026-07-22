---
description: Source-aware screening of untrusted content through randomized one-shot classifiers, durable quarantine, and capability-bounded fast paths.
delivered_by:
  - untrusted-input-quarantine-gateway
---

# Untrusted Input Screening — Spec

## What it is

TeleClaude screens content whose authenticated origin falls below the configured trust
threshold before that content enters a tool-capable agent session. The reusable screening
primitive cuts the complete input into random-length fragments, shuffles every fragment,
and presents the complete shuffled set in one shot to independent capability-free
classifiers. Semantic intent remains available for classification while the source text is
not presented as an executable instruction sequence.

The screening primitive is source-agnostic. Email, web forms, webhook payloads, imported
documents, uploaded files, and foreign content pasted or forwarded through a trusted
session use the same boundary. Trust comes from authenticated transport and provenance;
content cannot raise its own trust level, and forwarding does not transfer the forwarders
authority to the forwarded material.

Customer help-desk conversations use a separate low-latency path. Their sessions may
answer questions and use read-only tools, but cannot mutate business or platform state.
Authenticated members and administrators retain their full role-authorized tool surface
for their own instructions. Foreign content introduced into those sessions still passes
through screening before a tool-capable agent consumes it.

## Canonical fields

### Screening request

- `source_kind` — transport or ingestion class such as email, form, webhook, upload, or paste.
- `source_identity` — authenticated origin evidence supplied by the adapter, never parsed from content claims.
- `trust_level` — adapter-derived trust classification used against the configured screening threshold.
- `content_digest` — immutable digest of the original payload.
- `content` — original payload retained by the orchestrator and never treated as classifier instructions.

### Classification run

- `fragment_seed` — independently generated seed recorded for replay but hidden from the classifier.
- `fragments` — the complete payload cut at random-length boundaries and shuffled without source positions.
- `classifier` — model identity used for this independent judgment.
- `verdict` — `benign` or `flagged`.
- `reason_codes` — bounded reason-code values; no free-form classifier handover.

### Routing result

- Content is released only when every required independent classification returns `benign`.
- Any `flagged`, malformed, unavailable, or disagreeing result routes the original payload to quarantine.
- Quarantine is a durable review queue, never deletion. It preserves the original payload, provenance, all verdicts, and reason codes, and notifies the responsible people.
- A classifier receives no tools, credentials, writable filesystem, network access, session-management surface, or free-form downstream channel.
- Screening evidence is auditable and replayable without requiring a classifier to retain state between runs.

### Use cases

#### UC-UIS-SOURCE-ROUTING: Untrusted origin selects screening without trusting content claims

```gherkin
Given content arriving through an adapter with authenticated origin evidence below the configured trust threshold
When TeleClaude routes the content
Then the content enters the reusable screening primitive before any tool-capable agent can consume it
And sender names, addresses, signatures, or instructions inside the content cannot raise its trust level
```

#### UC-UIS-ONE-SHOT-RANDOMIZATION: Each classifier sees the complete shuffled message once

```gherkin
Given an untrusted payload selected for screening
When an independent classification run starts
Then the complete payload is cut into random-length fragments
And every fragment is shuffled and presented together in one classifier request
And no fragment carries its original position or ordering metadata
And the classifier receives no earlier run, progressive reveal, or retained prose context
```

#### UC-UIS-INDEPENDENT-CONSENSUS: Release requires independent benign judgments

```gherkin
Given an untrusted payload selected for screening
When the configured independent classifier runs complete with independently shuffled fragment sets
Then the payload is released only when every required run returns benign
And any flagged, disagreeing, malformed, or unavailable result routes the payload to quarantine
```

#### UC-UIS-DURABLE-QUARANTINE: Flagged content reaches responsible people without being lost

```gherkin
Given a payload whose screening result requires quarantine
When TeleClaude records the routing result
Then the original payload and its authenticated provenance remain durably available
And the classification verdicts and bounded reason codes remain attached
And the responsible people are notified through their configured delivery channels
And the payload is neither discarded nor delivered to the intended tool-capable agent
```

#### UC-UIS-HELPDESK-FAST-PATH: Customer help desk remains fast through capability restriction

```gherkin
Given a customer message entering the public help-desk path
When the help-desk session handles the message without screening latency
Then the session may answer questions and invoke read-only tools
And the execution boundary refuses business-state, platform-state, credential, deployment, and session-management mutations
```

#### UC-UIS-TRUSTED-AUTHORITY: Authenticated members retain their authorized tools

```gherkin
Given a member or administrator authenticated by the ingress adapter
When that person gives their own direct instruction
Then the session receives the tools authorized for that persons role
And the public customer help-desk restriction is not applied to that trusted instruction
```

#### UC-UIS-FOREIGN-CONTENT: Forwarded material does not inherit member authority

```gherkin
Given a trusted member session with tool authority
And the member pastes, forwards, uploads, or references content originating from another party
When the session attempts to consume that foreign content
Then TeleClaude evaluates the foreign contents own provenance
And content below the trust threshold enters screening before reaching the tool-capable session
```

#### UC-UIS-ADAPTER-INDEPENDENCE: Every ingestion surface reuses one primitive

```gherkin
Given two adapters ingesting equivalent untrusted content through different transports
When both adapters route the content
Then both call the same screening contract with normalized provenance
And neither adapter implements its own classifier, quarantine store, or escalation policy
```
