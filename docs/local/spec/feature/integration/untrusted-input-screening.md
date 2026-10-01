---
description: Source-aware screening of untrusted content through randomized one-shot classifiers, durable quarantine, and capability-bounded fast paths.
delivered_by:
  - untrusted-input-quarantine-gateway
---

# Untrusted Input Screening — Spec

## Required reads

- @~/.teleclaude/docs/general/policy/untrusted-input-handling.md

## What it is

TeleClaude routes inbound content by an adapter-derived disposition before that content
enters an agent session. Screened pooled input is stored as an immutable ingress object.
The reusable screening primitive reads that object inside an isolated DMZ, cuts its complete
normalized text into random-length fragments, shuffles every fragment, and presents the
complete shuffled set in one shot to independent capability-free classifiers. The mechanism
removes contiguous source ordering while preserving the fragments as classification evidence;
it does not claim that a classifier is infallible.

The screening primitive is source-agnostic. Email, web forms, webhook payloads, imported
documents, and uploaded files use the same ingress-object boundary. Trust comes from
authenticated transport and provenance; content cannot raise its own trust. Personal agents
pull email and other pooled content through screened-read tools. Raw pooled content is never
copied, pasted, or forwarded into their conversation sessions.

Customer help-desk conversations use a separate low-latency path. Their sessions may
answer questions and read only the public bundles mounted in their publication jail.
Authenticated members and administrators retain their full role-authorized tool surface
for direct input delivered through their authenticated interaction channels.

## Canonical fields

### Screening request

- `ingress_object_id` — opaque reference to immutable content in the DMZ store.
- `source_kind` — transport or ingestion class such as email, form, webhook, or upload.
- `source_identity` — authenticated origin evidence supplied by the adapter, never parsed from content claims.
- `disposition` — one of `direct_trusted`, `public_restricted`, `screened_pooled`, or `retrieval_restricted`.
- `content_digest` — immutable digest of the original payload.

### Normalization result

- `normalized_object_id` — opaque reference to isolated extracted text and metadata.
- `content_type` — detected media type retained with the original adapter declaration.
- `byte_size` — original payload size used for configured resource limits.
- `normalizer` — identity and version of the isolated extraction mechanism.
- `status` — `ready` or `quarantine`; unsupported, malformed, encrypted, and over-limit inputs never become `ready`.

### Classification run

- `fragment_seed` — independently generated seed recorded for replay but hidden from the classifier.
- `fragments` — the complete payload cut at random-length boundaries and shuffled without source positions.
- `classifier` — model identity used for this independent judgment.
- `verdict` — `benign` or `flagged`.
- `reason_codes` — bounded reason-code values; no free-form classifier handover.

### Routing result

- Content is released only when every required independent classification returns `benign`.
- Any `flagged`, malformed, timed-out, unavailable, or disagreeing result routes the original payload to quarantine.
- Quarantine is a durable review queue, never deletion. It preserves the original payload, provenance, all verdicts, and reason codes, and notifies the responsible people.
- A classifier receives no tools, credentials, writable filesystem, network access, session-management surface, or free-form downstream channel.
- Screening evidence is auditable and replayable without requiring a classifier to retain state between runs.
- Classifier unavailability retains the object for retry and raises a degraded-service notification; it never drops or partially releases content.

### Use cases

#### UC-UIS-SOURCE-ROUTING: Untrusted origin selects screening without trusting content claims

```gherkin
Given content arriving through an adapter with authenticated origin evidence
When TeleClaude routes the content
Then the policy router assigns exactly one disposition from direct_trusted, public_restricted, screened_pooled, or retrieval_restricted
And sender names, addresses, signatures, or instructions inside the content cannot raise its trust level
```

#### UC-UIS-DMZ-REFERENCE: Raw pooled content enters by immutable reference

```gherkin
Given external pooled content accepted by an ingress adapter
When the adapter hands the content to the screening boundary
Then the original bytes are stored as an immutable content-addressed ingress object
And orchestration receives only its opaque reference, digest, and typed provenance
And the raw content does not appear in command arguments, session prompts, clipboard handoffs, or free-form coordination messages
```

#### UC-UIS-ISOLATED-NORMALIZATION: Attachments are parsed before classification without escaping the DMZ

```gherkin
Given a screened ingress object containing text or an attachment
When normalization runs
Then an isolated normalizer with no business credentials or mutation capabilities produces text plus extraction metadata
And unsupported, malformed, encrypted, or over-limit input enters quarantine
And no payload is silently truncated or partially released
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

#### UC-UIS-DEGRADED-SERVICE: Screening outages preserve inbound business traffic

```gherkin
Given an ingress object whose required classifier is unavailable or times out
When screening cannot reach a complete decision
Then the object remains durably queued for retry
And the responsible people receive a degraded-service notification
And no content is lost, partially released, or silently accepted
```

#### UC-UIS-HELPDESK-FAST-PATH: Customer help desk remains fast through capability restriction

```gherkin
Given a customer message entering the public help-desk path
When the help-desk session handles the message without screening latency
Then the session may answer questions using only the public bundles mounted in its publication jail
And its tools are read-only over that published corpus
And internal documents, business records, credentials, deployment state, and session-management surfaces are absent from its readable context and tool surface
```

#### UC-UIS-TRUSTED-AUTHORITY: Authenticated members retain their authorized tools

```gherkin
Given a member or administrator authenticated by the ingress adapter
When that person gives their own direct instruction through the authenticated interaction channel
Then the session receives the tools authorized for that person's role
And the public customer help-desk restriction is not applied to that trusted instruction
```

#### UC-UIS-PULL-ONLY-POOL: Personal agents read external pooled content only through the gate

```gherkin
Given a personal agent whose member has connected an email or external-content source
When the personal agent requests an item from that source
Then the connector creates or resolves the immutable ingress object and applies screening before returning content
And no email or foreign payload is copied, pasted, forwarded, or injected into the personal-agent conversation outside that screened-read path
```

#### UC-UIS-RESTRICTED-RETRIEVAL: Agent-initiated browsing cannot carry mutation authority

```gherkin
Given a tool-capable agent requesting public or third-party free-form content during a task
When TeleClaude performs the retrieval
Then a read-only retrieval jail fetches and interprets the target without business or platform mutation tools
And the requesting agent receives cited evidence or a typed extraction
And the retrieved content cannot grant itself authority to trigger a consequential mutation
```

#### UC-UIS-DICTATED-CLAIM: Trusted speech authenticates intent but not repeated external facts

```gherkin
Given an authenticated member dictating an instruction through speech-to-text
And that instruction repeats a consequential claim originating from another party
When the agent evaluates a bank-detail, credential, access, deployment, or payment-control change
Then the member's authenticated channel establishes who requested the action
And the factual claim still requires authenticated business state or a separate trusted confirmation source
```

#### UC-UIS-ADAPTER-INDEPENDENCE: Every ingestion surface reuses one primitive

```gherkin
Given two adapters ingesting equivalent untrusted content through different transports
When both adapters route the content
Then both create the same ingress-object contract with normalized provenance
And both reuse the shared normalization, classification, quarantine, retry, and notification services
And neither adapter implements a local screening variant
```
