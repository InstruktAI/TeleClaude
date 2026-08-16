---
description: 'The closed header vocabulary prefixing text that enters an agent session: identity headers naming who authored content, control headers naming what daemon text is, and which of the two binds and reflects.'
visibility: 'internal'
---

# Message Headers — Spec

## What it is

Text arriving into an agent session's transcript may carry a leading bracketed
**header** naming where it came from. The header is the classification signal
available at candidate selection: the durable inbound receipt and the structured
peer bundle exist beforehand and remain the authority for authorship and
boundaries, but binding is the act of correlating those records to transcript
text, so eligibility at that moment is decided from the header alone.

Headers come in two kinds, distinguished by what their metadata is *for*:

- **Identity header** — answers *who authored this, and from where*. The text is
  content: authored by someone in another session (an agent, a role-bearing
  session, or a human) for a reader. It binds to the transcript turn it creates
  and reflects onto human-facing surfaces under its author's resolved identity.
- **Control header** — answers *what this text is*. There is no author. The
  platform emits it to drive an agent's own loop; it carries nothing about the
  work, and its instructions are addressed to a machine. It never binds and
  never reaches a human-facing surface.

A turn carrying no header at all is this session's own human speaking; genuine
human input is delivered unwrapped.

Every header is emitted by the platform from the closed vocabulary below, so
recognition is a match against that vocabulary by exact kind. Matching a control
kind by shared prefix instead is what allows an identity header that happens to
begin with the same characters to be read as control.

## Canonical fields

<!-- planned:peer-content-namespace-collision -->
The `[TeleClaude …]` prefix is reserved for control headers. No identity header
occupies it, and that reservation is what makes control recognition sound: a
control test can never match authored content, and content can never be mistaken
for machine text.
<!-- /planned:peer-content-namespace-collision -->

| Header                                                       | Producer                      | Kind     | Binds | Reflects to human surfaces |
| ------------------------------------------------------------ | ----------------------------- | -------- | ----- | -------------------------- |
| `[TeleClaude Notification]`                                  | daemon notification labels    | control  | no    | no                         |
| `[TeleClaude Input Request]`                                 | daemon notification labels    | control  | no    | no                         |
| `[TeleClaude Checkpoint] - `                                 | checkpoint surface            | control  | no    | no                         |
<!-- planned-change:peer-content-namespace-collision -->
| `[TeleClaude - Peer (session · author-token · utc-minute)]`  | peer segment header           | identity | yes   | yes                        |
<!-- change:peer-content-namespace-collision -->
| `[Peer (session · author-token · utc-minute)]`               | peer segment header           | identity | yes   | yes                        |
<!-- /planned-change:peer-content-namespace-collision -->
| `[Orchestrator (session) on computer]`                       | caller-origin identity header | identity | yes   | yes                        |
| `[Integrator (session) on computer]`                         | caller-origin identity header | identity | yes   | yes                        |
| `[System (session) on computer]`                             | caller-origin identity header | identity | yes   | yes                        |
| `[Worker (session) on computer]`                             | caller-origin identity header | identity | yes   | yes                        |
| `[Tasker (session) on computer]`                             | caller-origin identity header | identity | yes   | yes                        |
| `[Job Runner (session) on computer]`                         | caller-origin identity header | identity | yes   | yes                        |
| `[Agent - <agent> (session) on computer]`                    | caller-origin identity header | identity | yes   | yes                        |

A caller-origin identity header may carry an optional category segment, rendered
as `[<role> - <category> (session) on computer]`; the agent form uses that
segment to name the authoring agent.

### Why control headers are excluded from human surfaces

Exclusion is a property of the text, not a preference. A turn-completion notice
tells an agent which session to inspect; a checkpoint states an obligation the
agent must discharge; an input request solicits the loop. A human reader gains
nothing from any of them — the conversation they describe is already in front of
that reader — and cannot act on their instructions. Surfacing them displaces the
content a human is actually there to read.

### Identity resolution

An identity header's rendered author is presentation. Authorship is resolved
from the durable record and, where the authoring session runs an agent, resolves
to that agent's identity; a job role is orthogonal metadata that qualifies the
identity rather than replacing it. Rendered headers are never parsed to recover
authorship, segment boundaries, or loop-prevention facts.

## Known caveats

- Header text is presentation for the receiving agent and carries no attribution
  authority. Removing it from an entry, or forging it in a local body, changes
  nothing that was recorded.
- Legacy transcript entries predating a vocabulary change retain the header shape
  in force when they were written; recognizing them is bounded by the cutover
  that introduced the new shape and requires a correlated durable record, never
  text shape alone.

## See Also

- ~/.teleclaude/docs/general/policy/message-identity-headers.md — the reserved namespace, why an agent never authors a header, and how to read one.
- docs/project/spec/session-projection.md — per-recipient output visibility and the alias grammar applied when content reflects.
- docs/project/spec/feature/agent_runtime/session-input-delivery.md — how caller-origin identity headers are composed and bound.
- docs/project/spec/feature/agent_runtime/direct-conversation-links.md — peer segment structure and cross-share delivery.
