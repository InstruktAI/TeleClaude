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

<!-- planned:consolidate-injected-text-pipeline -->
That sentence binds the producing side as hard as the reading side: **every
text the platform injects into a session carries a header from this
vocabulary.** No daemon-authored text — a restart continuation, a listener
notice, any future injection — is ever delivered bare, because bare text is
the human's signature.

**Framing is paired and single-sourced.** An envelope that frames a body
derives its opening delimiter, closing delimiter, and any platform-appended
footer from one definition. A producer cannot emit an opener without its
close, so a body's extent is always marked rather than inferred from whatever
text follows it.
<!-- /planned:consolidate-injected-text-pipeline -->

### Classification taxonomy

Classifying a transcript entry answers one question with one typed kind, from
a closed set that is wider than the platform's own headers:

- **platform control** — the `[TeleClaude …]` vocabulary above;
- **identity content** — peer segments and caller-origin headers;
- **reminder** — the reminder envelopes below;
- **third-party runtime artifact** — text the agent CLI itself injects (hook
  feedback wrappers, XML-style tool frames, teammate-message blocks, an
  AGENTS.md instruction heading): not platform-authored, recognized by the
  narrow shapes that CLI emits, never content and never a human turn;
- **ordinary** — everything else, which is the session's human.

Every consumer that needs an entry's kind asks this one classification;
overlapping per-consumer predicates over the same text are a defect.

Every header is emitted by the platform from the closed vocabulary below, so
recognition is a match against that vocabulary by exact kind. Matching a control
kind by shared prefix instead is what allows an identity header that happens to
begin with the same characters to be read as control.

## Canonical fields

The `[TeleClaude …]` prefix is reserved for control headers. No identity header
occupies it, and that reservation is what makes control recognition sound: a
control test can never match authored content, and content can never be mistaken
for machine text.

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

<!-- planned:consolidate-injected-text-pipeline -->
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
<!-- /planned:consolidate-injected-text-pipeline -->


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
