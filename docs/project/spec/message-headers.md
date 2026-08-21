---
description: 'The closed header vocabulary prefixing text that enters an agent session: identity headers naming who authored content, control headers naming what daemon text is, and which of the two binds and reflects.'
visibility: 'internal'
---

# Message Headers — Spec

## What it is

<!-- planned-change:envelope-authoritative-classification -->
Text arriving into an agent session's transcript may contain one or more closed
platform envelopes alongside text typed locally by the session's human. Binding
first locates complete envelopes from the closed framing vocabulary, then
correlates each envelope with its durable accepted receipt and occurrence
identity. Rendered body equality and whole-entry equality are never correlation
evidence. Only the correlated envelope's recorded body span acquires its injected
classification and authorship; every span outside correlated envelopes remains
local human input, even when it resembles platform text.
<!-- change:envelope-authoritative-classification -->
Text arriving into an agent session's transcript may contain one or more closed
platform envelopes alongside prompt input typed into the session. Reading an
entry locates complete envelopes from the closed framing vocabulary and types
each one from its opening. A located envelope's body span carries that kind and
its authorship; every span outside a located envelope, within a user entry, is
prompt input. Classification is complete from the entry alone and never waits on
a correlated receipt, so no span is left untyped.
<!-- /planned-change:envelope-authoritative-classification -->

Headers come in three kinds, distinguished by what their metadata is _for_:

- **Identity header** — answers _who authored this, and from where_. The text is
  content: authored by someone in another session (an agent, a role-bearing
  session, or a human) for a reader. It binds to the transcript turn it creates
  and reflects onto human-facing surfaces under its author's resolved identity.
- **Control header** — answers _what this text is_. There is no author. The
  platform emits it to drive an agent's own loop; it carries nothing about the
  work, and its instructions are addressed to a machine. It never binds and
  never reaches a human-facing surface.
- **Reminder header** — identifies a typed reminder transcript entry. There is
  no external author: the owning agent authored the stored intent and the
  platform authored the lifecycle envelope. Armed, replaced, cancelled, and
  firing entries remain transcript source truth; a firing entry is the reminder
  acting now and enters the agent loop.

A turn carrying no header at all is this session's own human speaking; genuine
human input is delivered unwrapped.

That sentence binds the producing side as hard as the reading side: **every
text the platform injects into a session carries a header from this
vocabulary.** No daemon-authored text — a restart continuation, a listener
notice, any future injection — is ever delivered bare, because bare text is
the human's signature.

<!-- planned-change:envelope-authoritative-classification -->
**Framing is paired and single-sourced.** An envelope that frames a body
derives its opening delimiter, closing delimiter, and any platform-appended
footer from one definition. A producer cannot emit an opener without its
close, so a body's extent is always marked rather than inferred from whatever
text follows it.
<!-- change:envelope-authoritative-classification -->
**Framing is single-sourced, and its closure is declared.** One definition per
header declares its opening delimiter and its closure discipline. A **paired**
header frames a body and derives its closing delimiter from that same
definition; a producer cannot emit its opener without its close, so the body's
extent is always marked rather than inferred. An **auto-closed** header carries
no body and is complete on its own. Which discipline a header follows is read
from the definition, never guessed from whether a closing delimiter happens to
appear, and one header never carries both.
<!-- /planned-change:envelope-authoritative-classification -->

### Classification taxonomy

Classifying accepted text or a receiptless native span answers one question with
one typed kind, from a closed set that is wider than the platform's own headers:

<!-- planned-change:envelope-authoritative-classification -->
- **platform control** — a correlated `[TeleClaude …]` envelope;
- **identity content** — a correlated peer or caller-origin envelope;
- **reminder** — a correlated reminder envelope;
- **third-party runtime artifact** — a complete receiptless entry emitted by the
  agent CLI itself (hook feedback wrappers, XML-style tool frames,
  teammate-message blocks, an AGENTS.md instruction heading): not
  platform-authored, never content, and never a human turn;
- **ordinary** — every receiptless ordinary entry and every native-entry span
  outside correlated envelopes, which belongs to the session's human.
<!-- change:envelope-authoritative-classification -->
- **platform control** — a `[TeleClaude …]` envelope;
- **identity content** — a peer or caller-origin envelope;
- **reminder** — a reminder envelope;
- **third-party runtime artifact** — a complete entry emitted by the agent CLI
  itself, recognized from that runtime's own declared wrapper vocabulary: not
  platform-authored, never content, and never a human turn;
- **ordinary** — every other entry and every native-entry span outside an
  envelope, which is prompt input typed into the session.
<!-- /planned-change:envelope-authoritative-classification -->

<!-- planned-change:envelope-authoritative-classification -->
One native entry may therefore carry several ordered classified parts. Every
consumer asks the durable binding for each part's classification; overlapping
per-consumer predicates over rendered text are a defect.

Every platform envelope is emitted from the closed vocabulary below. Candidate
recognition requires an exact opening kind and its matching derived close;
correlation to an accepted receipt establishes whether that candidate is a real
injection. A shared prefix, a bare opener, or an uncorrelated lookalike in local
text establishes nothing.
<!-- change:envelope-authoritative-classification -->
One native entry may therefore carry several ordered classified parts. Every
consumer reads that same segmentation from the entry's own envelopes; a
per-consumer predicate over rendered text is a defect.

Every platform envelope is emitted from the closed vocabulary below. Recognition
requires an exact opening kind from that vocabulary and, for a paired header, its
matching derived close; an auto-closed header is complete at its opening. A
shared prefix or an opener outside the vocabulary establishes nothing.
<!-- /planned-change:envelope-authoritative-classification -->

## Canonical fields

The `[TeleClaude …]` prefix is reserved for control headers. No identity header
occupies it, and that reservation is what makes control recognition sound: a
control test can never match authored content, and content can never be mistaken
for machine text.

<!-- planned-change:envelope-authoritative-classification -->
| Header                                         | Producer                      | Kind     | Binds | Reflects to human surfaces |
| ---------------------------------------------- | ----------------------------- | -------- | ----- | -------------------------- |
| `[TeleClaude Notification]`                    | daemon notification labels    | control  | no    | no                         |
| `[TeleClaude Input Request]`                   | daemon notification labels    | control  | no    | no                         |
| `[TeleClaude Checkpoint] - `                   | checkpoint surface            | control  | no    | no                         |
| `[Peer (session · author-token · utc-minute)]` | peer segment header           | identity | yes   | yes                        |
| `[Orchestrator (session) on computer]`         | caller-origin identity header | identity | yes   | yes                        |
| `[Integrator (session) on computer]`           | caller-origin identity header | identity | yes   | yes                        |
| `[System (session) on computer]`               | caller-origin identity header | identity | yes   | yes                        |
| `[Worker (session) on computer]`               | caller-origin identity header | identity | yes   | yes                        |
| `[Tasker (session) on computer]`               | caller-origin identity header | identity | yes   | yes                        |
| `[Job Runner (session) on computer]`           | caller-origin identity header | identity | yes   | yes                        |
| `[Agent - <agent> (session) on computer]`      | caller-origin identity header | identity | yes   | yes                        |
<!-- change:envelope-authoritative-classification -->
| Header                                         | Producer                      | Kind     | Closure     | Binds | Reflects to human surfaces |
| ---------------------------------------------- | ----------------------------- | -------- | ----------- | ----- | -------------------------- |
| `[TeleClaude Notification]`                    | daemon notification labels    | control  | paired      | no    | no                         |
| `[TeleClaude Wake]`                            | control-delivery idle wake    | control  | auto-closed | no    | no                         |
| `[TeleClaude Restart Continuation]`            | agent restart                 | control  | paired      | no    | no                         |
| `[TeleClaude Checkpoint] - `                   | checkpoint surface            | control  | paired      | no    | no                         |
| `[Peer (session · author-token · utc-minute)]` | peer segment header           | identity | paired      | yes   | yes                        |
| `[Orchestrator (session) on computer]`         | caller-origin identity header | identity | paired      | yes   | yes                        |
| `[Integrator (session) on computer]`           | caller-origin identity header | identity | paired      | yes   | yes                        |
| `[System (session) on computer]`               | caller-origin identity header | identity | paired      | yes   | yes                        |
| `[Worker (session) on computer]`               | caller-origin identity header | identity | paired      | yes   | yes                        |
| `[Tasker (session) on computer]`               | caller-origin identity header | identity | paired      | yes   | yes                        |
| `[Job Runner (session) on computer]`           | caller-origin identity header | identity | paired      | yes   | yes                        |
| `[Agent - <agent> (session) on computer]`      | caller-origin identity header | identity | paired      | yes   | yes                        |
<!-- /planned-change:envelope-authoritative-classification -->

A caller-origin identity header may carry an optional category segment, rendered
as `[<role> - <category> (session) on computer]`; the agent form uses that
segment to name the authoring agent.

### Reminder and response-boundary envelopes

`[Reminder <slug> ...]` is a reminder-kind transcript header and the matching
footer is `[/Reminder <slug>]`. Lifecycle records name `armed`, `replaced`, or
`cancelled`; a firing reminder names its schedule or typed event anchor without
a separate `due` status. The platform derives both delimiters from the durable
reminder record. The body is the stored agent-authored intent; neither delimiter
is parsed to recover reminder identity or lifecycle state.

<!-- planned-change:quiet-reminders -->
Projection carries the typed reminder payload through the existing category and
routing contracts. Human-facing UI adapters do not reproduce either bracketed
delimiter: they render envelope-free Markdown fields and localize structured
instants from TeleClaude's configured person location and time zone.
<!-- change:quiet-reminders -->
A reminder envelope appears only inside a delivered firing. Reminder records
are readable through the service's reminder inspection surfaces.
<!-- /planned-change:quiet-reminders -->

<!-- planned-change:quiet-reminders -->
Every identity-bearing non-human conversational envelope also carries a
platform-authored response-boundary footer, outside the sender-authored body:

```text
[Mandatory response boundary]
After preparing your response, arm the prescribed halt-to-respond reminder as your final tool action. Then emit only that response and yield.
[/Mandatory response boundary]
```
<!-- change:quiet-reminders -->
Every identity-bearing non-human conversational envelope also carries a
platform-authored response-boundary footer, outside the sender-authored body:

```text
[Mandatory response boundary]
Respond, then yield. If this message interrupts in-progress work whose resumption needs a guarantee, arm the prescribed halt-to-respond reminder as your final tool action before emitting the response.
[/Mandatory response boundary]
```
<!-- /planned-change:quiet-reminders -->

The footer applies only when the recipient authors a response. It does not turn
control notifications, checkpoints, reminder envelopes, or silent directives
into response-bearing conversation, and it is never attributed to the sender.

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

That resolution happens once per event, and every surface renders from the one
result: the pane header an agent reads and the alias a human sees on Discord
present the same identity — agent primary, job role as qualifier, a
machine-role label only for a session running no agent. Two surfaces
disagreeing about who spoke is a defect in the rendering, never two truths.

**Human-facing copy omits identity-header framing on every lane.** Identity
headers and their closing delimiters are presentation for the receiving agent;
the human-facing copy of a message renders its body under the author's resolved
identity with that framing stripped, on the peer lane, the caller-origin lane,
and every future lane alike.


## Known caveats

<!-- planned-change:envelope-authoritative-classification -->
- Header text is presentation for the receiving agent and carries no attribution
  authority. Removing it from an entry, or forging it in a local body, changes
  nothing that was recorded.
- Legacy transcript entries predating a vocabulary change retain the header shape
  in force when they were written; recognizing them is bounded by the cutover
  that introduced the new shape and requires a correlated durable record, never
  text shape alone.
<!-- change:envelope-authoritative-classification -->
- Header text carries the boundary and kind of the block it opens. Inside another
  envelope's body it is body content, because bodies are never inspected; in an
  agent's own output it is that agent's content. Neither position re-frames the
  entry around it.
- Legacy transcript entries predating a vocabulary change retain the header shape
  in force when they were written; recognizing them is bounded by the cutover
  that introduced the new shape.
<!-- /planned-change:envelope-authoritative-classification -->

## See Also

- ~/.teleclaude/docs/general/policy/message-identity-headers.md — the reserved namespace, why an agent never authors a header, and how to read one.
- docs/project/spec/session-projection.md — per-recipient output visibility and the alias grammar applied when content reflects.
- docs/project/spec/feature/agent_runtime/session-input-delivery.md — how caller-origin identity headers are composed and bound.
- docs/project/spec/feature/agent_runtime/direct-conversation-links.md — peer segment structure and cross-share delivery.
