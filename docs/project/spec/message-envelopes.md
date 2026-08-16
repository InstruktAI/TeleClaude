---
description: 'The bracketed envelope vocabulary prefixing text that enters an agent session: which envelopes denote authored content that binds and reflects, which denote daemon control that never does, and the discriminator between them.'
visibility: 'internal'
---

# Message Envelopes — Spec

## What it is

Text arriving into an agent session's transcript carries a leading bracketed
envelope naming where it came from. The envelope is the classification signal
available at candidate selection: the durable inbound receipt and the structured
peer bundle exist beforehand and remain the authority for authorship and
boundaries, but binding is the act of correlating those records to transcript
text, so eligibility at that moment is decided from the envelope alone.

Two classes, separated by one question — **who authored this text, and for
whom.**

- **Content** — authored by someone in another session (an agent, a role-bearing
  session, or a human) for a reader. It binds to the transcript turn it creates
  and reflects onto human-facing surfaces under its author's resolved identity.
- **Daemon control** — emitted by the platform to drive an agent's own loop.
  Nobody authored it for a reader: it carries nothing about the work, and its
  instructions ("inspect that session", "run this maintenance action") are
  addressed to a machine and are not actionable by a human. It never binds and
  never reaches a human-facing surface.

Every envelope is emitted by the platform from the closed vocabulary below, so
classification is a match against that vocabulary by exact kind. Matching a
control kind by shared prefix instead is what allows a content envelope that
happens to begin with the same characters to be read as control.

## Canonical fields

<!-- planned:peer-content-namespace-collision -->
The `[TeleClaude …]` namespace is reserved for daemon control. No content
envelope occupies it, and reservation is what makes control classification
sound: a control test can never match authored content, and a content envelope
can never be mistaken for machine chatter.
<!-- /planned:peer-content-namespace-collision -->

| Envelope                                                     | Producer                              | Class   | Binds | Reflects to human surfaces |
| ------------------------------------------------------------ | ------------------------------------- | ------- | ----- | -------------------------- |
| `[TeleClaude Notification]`                                  | daemon notification labels            | control | no    | no                         |
| `[TeleClaude Input Request]`                                 | daemon notification labels            | control | no    | no                         |
| `[TeleClaude Checkpoint] - `                                 | checkpoint surface                    | control | no    | no                         |
<!-- planned-change:peer-content-namespace-collision -->
| `[TeleClaude - Peer (session · author-token · utc-minute)]`  | peer segment header                   | content | yes   | yes                        |
<!-- change:peer-content-namespace-collision -->
| `[Peer (session · author-token · utc-minute)]`               | peer segment header                   | content | yes   | yes                        |
<!-- /planned-change:peer-content-namespace-collision -->
| `[Orchestrator (session) on computer]`                       | caller-origin identity header         | content | yes   | yes                        |
| `[Integrator (session) on computer]`                         | caller-origin identity header         | content | yes   | yes                        |
| `[System (session) on computer]`                             | caller-origin identity header         | content | yes   | yes                        |
| `[Worker (session) on computer]`                             | caller-origin identity header         | content | yes   | yes                        |
| `[Tasker (session) on computer]`                             | caller-origin identity header         | content | yes   | yes                        |
| `[Job Runner (session) on computer]`                         | caller-origin identity header         | content | yes   | yes                        |
| `[Agent - <agent> (session) on computer]`                    | caller-origin identity header         | content | yes   | yes                        |

A caller-origin header may carry an optional category segment, rendered as
`[<role> - <category> (session) on computer]`; the agent form uses that segment
to name the authoring agent.

### Why control text is excluded from human surfaces

Exclusion is a property of the text, not a preference. A turn-completion notice
tells an agent which session to inspect; a checkpoint states an obligation the
agent must discharge; an input request solicits the loop. A human reader gains
nothing from any of them — the conversation they describe is already in front of
that reader — and cannot act on their instructions. Surfacing them displaces the
content a human is actually there to read.

### Identity on content envelopes

A content envelope's rendered author is presentation. Authorship is resolved
from the durable record and, where the authoring session runs an agent, resolves
to that agent's identity; a job role is orthogonal metadata that qualifies the
identity rather than replacing it. Rendered envelopes are never parsed to
recover authorship, segment boundaries, or loop-prevention facts.

## Known caveats

- Envelope text is presentation for the receiving agent and carries no
  attribution authority. Removing it from an entry, or forging it in a local
  body, changes nothing that was recorded.
- Legacy transcript entries predating a namespace change retain the envelope
  shape in force when they were written; recognizing them is bounded by the
  cutover that introduced the new shape and requires a correlated durable
  record, never text shape alone.

## See Also

- docs/project/spec/session-projection.md — per-recipient output visibility and the alias grammar applied when content reflects.
- docs/project/spec/feature/agent_runtime/session-input-delivery.md — how caller-origin headers are composed and bound.
- docs/project/spec/feature/agent_runtime/direct-conversation-links.md — peer segment structure and cross-share delivery.
