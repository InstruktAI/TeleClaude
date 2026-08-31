---
description: 'The closed header vocabulary prefixing text that enters an agent session: identity headers naming who authored content, control headers naming what daemon text is, and which of the two binds and reflects.'
visibility: 'internal'
---

# Message Headers — Spec

## What it is

Text arriving into an agent session's transcript may contain one or more closed
platform envelopes alongside prompt input typed into the session. Reading an
entry locates complete envelopes from the closed framing vocabulary and types
each one from its opening. A located envelope's body span carries that kind and
its authorship; every span outside a located envelope, within a user entry, is
prompt input. Classification is complete from the entry alone and never waits on
a correlated receipt, so no span is left untyped.

Headers come in three kinds, distinguished by what their metadata is _for_:

- **Identity header** — answers _who authored this, and from where_. The text is
  content: authored by someone in another session (an agent, a role-bearing
  session, or a human) for a reader. It contributes one authored segment to the
  transcript turn it creates and reflects onto human-facing surfaces under its
  author's resolved identity.
- **Control header** — answers _what this text is_. There is no author. The
  platform emits it to drive an agent's own loop; it carries nothing about the
  work, and its instructions are addressed to a machine. It carries no
  authored content and never reaches a human-facing surface.
- **Reminder header** — identifies a typed reminder transcript entry. There is
  no external author: the owning agent authored the stored intent and the
  platform authored the lifecycle envelope. Armed, replaced, cancelled, and
  firing entries remain transcript source truth; a firing entry is the reminder
  acting now and enters the agent loop.

A turn carrying no header at all is this session's own human speaking; genuine
human input is delivered unwrapped.

That sentence binds the native user-entry channel as hard as the reading side:
**every text the platform injects through that channel carries a header from
this vocabulary.** No daemon-authored native user entry — a restart
continuation or any future injection — is delivered bare, because bare text is
the human's signature. Control payloads delivered through an agent runtime's
hook boundary use that runtime's declared wrapper instead and never enter as
unwrapped prompt text.

**Framing is single-sourced, and its closure is declared.** One definition per
header declares its opening delimiter and its closure discipline. A **paired**
header frames a body and derives its closing delimiter from that same
definition; a producer cannot emit its opener without its close, so the body's
extent is always marked rather than inferred. An **auto-closed** header carries
no body and is complete on its own. Which discipline a header follows is read
from the definition, never guessed from whether a closing delimiter happens to
appear, and one header never carries both.

### Classification taxonomy

Classifying accepted text or a receiptless native span answers one question with
one typed kind, from a closed set that is wider than the platform's own headers:

- **platform control** — a `[TeleClaude …]` envelope;
- **identity content** — a peer or caller-origin envelope;
- **reminder** — a reminder envelope;
- **third-party runtime artifact** — a complete entry emitted by the agent CLI
  itself, recognized from that runtime's own declared wrapper vocabulary: not
  platform-authored, never content, and never a human turn;
- **ordinary** — a user entry, or a span within one lying outside every envelope:
  prompt input typed into the session. An assistant entry is the agent's own
  output and is not classified by this taxonomy.

One native entry may therefore carry several ordered classified parts. Every
consumer reads that same segmentation from the entry's own envelopes; a
per-consumer predicate over rendered text is a defect.

Every platform envelope is emitted from the closed vocabulary below. Recognition
requires an exact opening kind from that vocabulary and, for a paired header, its
matching derived close; an auto-closed header is complete at its opening. A
shared prefix or an opener outside the vocabulary establishes nothing.

## Canonical fields

The `[TeleClaude …]` prefix is reserved for control headers. No identity header
occupies it, and that reservation is what makes control recognition sound: a
control test can never match authored content, and content can never be mistaken
for machine text.

| Header                                                 | Producer                      | Kind     | Closure     | Authored content | Reflects to human surfaces |
| ------------------------------------------------------ | ----------------------------- | -------- | ----------- | ---------------- | -------------------------- |
| `[TeleClaude Notification]`                            | legacy notification entries   | control  | paired      | no               | no                         |
| `[TeleClaude Wake]`                                    | control-delivery idle wake    | control  | auto-closed | no               | no                         |
<!-- planned-change:restart-continuation-via-control-delivery -->
| `[TeleClaude Restart Continuation]`                    | agent restart                 | control  | paired      | no               | no                         |
<!-- change:restart-continuation-via-control-delivery -->
| `[TeleClaude Restart Continuation]`                    | historical restart entries    | control  | paired      | no               | no                         |
<!-- /planned-change:restart-continuation-via-control-delivery -->
| `[TeleClaude Checkpoint]`                              | checkpoint surface            | control  | paired      | no               | no                         |
| `[Peer (session · author-token · utc-minute)]`         | peer segment header           | identity | paired      | yes              | yes                        |
| `[Orchestrator (session) on computer · utc-minute]`    | caller-origin identity header | identity | paired      | yes              | yes                        |
| `[Integrator (session) on computer · utc-minute]`      | caller-origin identity header | identity | paired      | yes              | yes                        |
| `[System (session) on computer · utc-minute]`          | caller-origin identity header | identity | paired      | yes              | yes                        |
| `[Worker (session) on computer · utc-minute]`          | caller-origin identity header | identity | paired      | yes              | yes                        |
| `[Tasker (session) on computer · utc-minute]`          | caller-origin identity header | identity | paired      | yes              | yes                        |
| `[Job Runner (session) on computer · utc-minute]`      | caller-origin identity header | identity | paired      | yes              | yes                        |
| `[Agent - <agent> (session) on computer · utc-minute]` | caller-origin identity header | identity | paired      | yes              | yes                        |

<!-- planned:restart-continuation-via-control-delivery -->
Restart continuation remains a semantic control envelope at the runtime hook
boundary. Its paired bracket form is recognized for historical transcript
entries only. A resumed session receives `[TeleClaude Wake]` as the sole
foreground marker, and the prompt-submission boundary carries the continuation
body to the agent through the runtime's context-injection codec.
<!-- /planned:restart-continuation-via-control-delivery -->

A caller-origin identity header may carry an optional category segment, rendered
as `[<role> - <category> (session) on computer · utc-minute]`; the agent form uses
that segment to name the authoring agent. `utc-minute` is the send-moment
occurrence time truncated to the minute in UTC — the same shared element the peer
and action envelopes carry. It is rendered once into the opening and the paired
close is derived from it, so the two never disagree.

### One model, two codecs

The registry owns one semantic envelope model: kind, label, closure discipline,
structured header fields, and body. Exactly two codecs render that model:

- The **bracket codec** renders every envelope on a surface a human can read,
  including peer and caller-identity transcript content and the content-free
  idle-wake marker visible in the session composer. It also renders the
  output-only human-action family as `[Action (<topic> · <utc-minute>)]` with
  the paired close `[/Action]`; that family never enters the native-user-entry
  classifier and never occupies the reserved `[TeleClaude …]` control
  namespace.
- The **XML codec** renders control payloads injected through an agent
  runtime's hook boundary. A paired model renders an opening element, body,
  and matching close; an auto-closed model renders a self-closing element.

Both codecs read the same registry entry. Neither declares a label, kind, or
closure rule of its own, and no third surface introduces another grammar.

### Reminder envelopes

`[Reminder <slug> ...]` is a reminder-kind transcript header and the matching
footer is `[/Reminder <slug>]`. Lifecycle records name `armed`, `replaced`, or
`cancelled`; a firing reminder names its schedule or typed event anchor without
a separate `due` status. The platform derives both delimiters from the durable
reminder record. The body is the stored agent-authored intent; neither delimiter
is parsed to recover reminder identity or lifecycle state.

A reminder envelope appears only inside a delivered firing. Reminder records
are readable through the service's reminder inspection surfaces.

### Why control headers are excluded from human surfaces

Exclusion is a property of the text, not a preference. A turn-completion notice
tells an agent which session to inspect; a checkpoint states an obligation the
agent must discharge; a restart continuation resumes the interrupted loop. A human reader gains
nothing from any of them — the conversation they describe is already in front of
that reader — and cannot act on their instructions. Surfacing them displaces the
content a human is actually there to read.

### Identity resolution

An identity header's rendered author is presentation; what may be read back from
it turns on what the field is. A **self-describing** field carries the fact in a
closed, validated vocabulary — the peer header's author token
(`human:<display>`, `agent:<runtime>/<thinking-mode>`, `machine:<role>`) is the
author snapshot itself, so decoding it recovers authorship, and a forged token
grants no identity its own text does not already state. A **pointer** field
names an entity without carrying it — the caller-origin header's session id —
and is never followed to recover authorship: that resolves from the durable
record, and where the authoring session runs an agent it resolves to that
agent's identity, with a job role as orthogonal metadata qualifying the identity
rather than replacing it. Rendered framing carries the boundary and kind of the
span it opens, which is how a span is located at all; it never carries
loop-prevention facts, which compare structured source session ids.

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

- Header text carries the boundary and kind of the block it opens. Inside another
  envelope's body it is body content, because bodies are never inspected; in an
  agent's own output it is that agent's content. Neither position re-frames the
  entry around it.
- Legacy transcript entries predating a vocabulary change retain the header shape
  in force when they were written; recognizing them is bounded by the cutover
  that introduced the new shape.

## See Also

- ~/.teleclaude/docs/general/policy/message-identity-headers.md — the reserved namespace, why an agent never authors a header, and how to read one.
- docs/project/spec/session-projection.md — per-recipient output visibility and the alias grammar applied when content reflects.
- docs/project/spec/feature/agent_runtime/session-input-delivery.md — how caller-origin identity headers are composed and bound.
- docs/project/spec/feature/agent_runtime/direct-conversation-links.md — peer segment structure and cross-share delivery.
