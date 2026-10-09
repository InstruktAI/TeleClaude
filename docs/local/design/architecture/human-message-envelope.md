---
description: Shared semantic envelope for human-facing authorship, provenance, occurrence time, and surface-specific rendering.
---

# Human-Facing Message Envelope — Design

## Purpose

Give every human-facing TeleClaude message enough identity and context to be
understood without promoting transport or persistence mechanics into message
copy. The envelope carries shared meaning; conversation and operational
surfaces apply their own renderer contracts.

## Inputs/Outputs

**Inputs:**

- The actual author or operation responsible for the message.
- Stable source identity and session provenance where a session is involved.
- Original occurrence time at full stored precision.

- Human-facing content, or the facts an event states.

- Surface-independent presentation identity.

**Outputs:**

- Structured provenance retained independently of rendered text.

- A surface-specific rendering produced by the conversation-delivery or
  notification-messages contract.

- Human-visible time only where it helps interpret the message; exact time
  remains available in structured state.

## Invariants

- **Meaning precedes rendering.** Producers supply author, provenance, time,
  and content once. Renderers never reconstruct those facts from display text.
- **Lineage is not authorship** (`general/concept/lineage-vs-authorship`):
  account lineage never substitutes for the human, agent, or machine that
  actually authored a message.
- **One source of truth for human-facing rendering.** For a message rendered to
  a person, structured fields are authoritative and headers, aliases, cards, and
  notification text are presentation. Agent-facing transcript classification is
  governed separately: there the platform's own envelope delimiters carry the
  authority.
- **Occurrence survives relay.** Forwarding preserves the original author,
  source, and occurrence time while recording relay progress separately.
- **Persistence metadata stays metadata.** Row identifiers, event types,
  attempts, cursors, and create/update verbs do not become message copy.
- **Privacy survives observability.** Operational logs carry structured,
  body-free metadata at policy-defined levels and never copy conversation
  bodies, credentials, or personal payloads.

## Primary flows

```mermaid
flowchart LR
    S[Source turn or event] --> E[Structured semantic envelope]
    E --> C[Conversation renderer]
    E --> N[Notification message renderer]
    E --> L[Body-free structured observability]
```

Conversation rendering answers who spoke and from where. Notification rendering
answers what happened, to which thing, on which computer and when. Both consume
the same shared provenance principles without sharing a universal output string.

## Failure modes

- Parsing rendered human-facing copy to recover provenance creates a second,
  ambiguous source of truth. This concerns rendered presentation, never the
  platform's own transcript envelopes, whose delimiters are authoritative.
- Treating lineage as authorship attributes autonomous work to the account
  owner rather than its actual author.
- Logging message bodies leaks conversation content without improving delivery
  diagnosis.

- Reusing one renderer across conversation and notification surfaces hides the
  question each surface must answer.

## See Also

- docs/local/design/architecture/conversation-delivery.md

- docs/local/design/architecture/notification-delivery.md
