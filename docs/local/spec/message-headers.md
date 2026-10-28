---
description: 'The closed header vocabulary prefixing text that enters an agent session: identity headers naming who authored content, control headers naming what daemon text is, and which of the two binds and reflects.'
visibility: 'internal'
---

# Message Headers — Spec

## What it is

Text arriving into an agent session's transcript may contain complete platform
envelopes alongside prompt input typed into the same entry. Recognition asks
only whether a registered opening and its declared closure identify an
envelope-shaped span. A recognized span carries the registered kind and the
header fields as written; its body is opaque. Every other span is prompt input
from the human in this session. Classification always covers the whole entry:
an unrecognized span is ordinary input, never an error that can stop projection,
reflection, or relay of that span or its neighbors.

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

**Framing is single-sourced, and its closure is declared.** One registry
definition declares each opening delimiter and its closure discipline. A
**paired** envelope is recognizable when its registered opening and derived
closing delimiter identify the span; an **auto-closed** envelope is complete at
its opening. The writer emits that shape. The reader neither repairs nor
rejects text that lacks it: such text remains ordinary human input, while
recognizable neighboring envelopes remain independently classifiable.

### Classification taxonomy

Classifying accepted text or a receiptless native span answers one question with
one typed kind, from a closed set that is wider than the platform's own headers:

- **platform control** — a `[TeleClaude …]` envelope;
- **identity content** — a peer or caller-origin envelope;
- **reminder** — a reminder envelope;
- **command loader** — the platform-generated dispatch text that makes a
  command document the session's instruction set, recognized as one complete
  text from the grammar the registry module owns alongside its renderer. It is
  never human-authored content, never eligible as a human-input recency
  signal, and never reaches a human-facing surface. It is still the prompt
  that opens the agent's turn, so the output answering it belongs to that
  turn like the output answering any authored input;
- **runtime artifact** — a complete entry emitted by the agent CLI, recognized
  from that runtime's declared structural vocabulary: never human-authored
  content and never eligible as a human-input recency signal;
- **ordinary** — a user entry, or a span within one lying outside every envelope:
  prompt input typed into the session. An assistant entry is the agent's own
  output and is not classified by this taxonomy.

One native entry may therefore carry several ordered classified parts. Every
consumer reads that same segmentation from the entry's own envelopes; a
per-consumer predicate over rendered text is a defect.

Every platform envelope is emitted from the closed vocabulary below.
Recognition uses only the registered delimiter shape: an exact opening kind
and, for paired envelopes, its derived close. The body is never scanned for
validity, header fields are never checked against a second vocabulary, and no
separator convention is a recognition precondition. Text that does not form a
complete registered envelope establishes no platform identity and remains
ordinary human input.

## Canonical fields

The `[TeleClaude …]` prefix is reserved for control headers. No identity header
occupies it, and that reservation is what makes control recognition sound: a
control test can never match authored content, and content can never be mistaken
for machine text.

| Header                                                          | Producer                      | Kind     | Closure     | Authored content | Reflects to human surfaces |
| --------------------------------------------------------------- | ----------------------------- | -------- | ----------- | ---------------- | -------------------------- |
| `[TeleClaude Notification]`                                     | legacy notification entries   | control  | paired      | no               | no                         |
| `[TeleClaude Wake]`                                             | control-delivery idle wake    | control  | auto-closed | no               | no                         |
| `[TeleClaude Restart Continuation]`                             | historical restart entries    | control  | paired      | no               | no                         |
| `[TeleClaude Handoff]`                                          | agent handoff continuation    | control  | paired      | no               | no                         |
| `[TeleClaude Checkpoint]`                                       | checkpoint surface            | control  | paired      | no               | no                         |
| `[Peer (session · author-token · utc-minute)]`                  | peer segment header           | identity | paired      | yes              | yes                        |
| `[<label> (session) on computer · utc-minute · occurrence-key]` | caller-origin identity header | identity | paired      | yes              | yes                        |

Restart continuation is a semantic control envelope at the runtime hook
boundary. Its paired bracket form is recognized for historical transcript
entries only. A resumed session receives `[TeleClaude Wake]` as the sole
foreground marker, and the prompt-submission boundary carries the continuation
body to the agent through the runtime's context-injection codec.

Handoff continuation is a paired platform-control envelope supplied as the
fresh successor's first startup input. Its body may carry the session's command
loader and handoff context, but it remains daemon-authored control text: it does
not establish human authorship, update the last visible human input, or reflect
onto a human-facing surface.

A caller-origin identity header may carry an optional category segment, rendered
as `[<role> - <category> (session) on computer · utc-minute · occurrence-key]`;
the agent form uses that segment to name the authoring agent. `utc-minute` is the
send-moment occurrence time truncated to the minute in UTC. `occurrence-key` is
the opaque durable key already owned by the accepted input row; it correlates the
envelope to that occurrence and carries no author fields or attribution authority.
Both values are rendered once into the opening and the paired close is derived
from it, so the two never disagree.

The label names who is speaking: `Agent` for a session running an agent, whose
category carries the agent and the session's role; the session's own role name
for a session that carries a role and runs no agent; `System` for the daemon.
The label is a field of the shape, like the session and the computer: any label
in this shape is a caller-origin header, and recognition never checks it against
a list.

During mixed-version operation, the caller opening recognizer accepts both the
keyed and preceding keyless shape. An upgraded target canonicalizes a keyless
live caller envelope from the command's structured caller metadata and durable
occurrence key before accepting it into the native-entry path; it never parses
the keyless header for author identity. An older target treats the added final
field as part of the already-open caller delimiter and derives its matching
close from that complete opening. The keyless transition remains a compatibility
reader only; upgraded writers emit the keyed shape.

### One model, two codecs

The registry owns one semantic envelope model: kind, label, closure discipline,
structured header fields, and body. Exactly two codecs render that model:

- The **bracket codec** renders every envelope on a surface a human can read,
  including peer and caller-identity transcript content and the content-free
  idle-wake marker visible in the session composer.

- The **XML codec** renders control payloads injected through an agent
  runtime's hook boundary. A paired model renders an opening element, body,
  and matching close; an auto-closed model renders a self-closing element.

Both codecs read the same registry entry. Neither declares a label, kind, or
closure rule of its own, and no third surface introduces another grammar.

### Occurrence moments on control envelopes

A control envelope that wakes an agent to act on a past event states that
event's moments as envelope fields, so the receiver judges its own lag; the
platform never states a lag. The XML codec renders the fields as attributes;
bracket headers stay as the table shows. Moments are UTC to the second, and
they survive relay as the human-facing envelope's occurrence does
(`local/projects/teleclaude/design/architecture/human-message-envelope`).

- A turn-ending, attention, or operation-outcome notification carries
  `occurred_at`: the moment the agent's stop hook fired, the attention was
  observed or an inferred stall or delivery block was inferred, or the
  operation reached its terminal state.
- A reminder firing carries `armed_at`, `due_at` (the deadline that fired), and
  `occurred_at` (the moment it fired); a recurring firing adds `interval` and
  `next_fire_at`.
- A moment the producer does not know is omitted, never replaced by the
  delivery moment. A forwarded notification carries the source computer's
  moment across the transport.
- Other control envelopes carry no moment.

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

An identity header's rendered author is presentation. The peer header's author
token (`human:<display>`, `agent:<runtime>/<thinking-mode>`,
`machine:<role>`) is the author snapshot carried by the envelope itself. The
reader trusts and presents that token; it does not reject an otherwise
recognized envelope because the token is unknown to a local enum. Known tokens
retain their richer alias and avatar presentation, while an unknown token
degrades to its own carried text. The peer header's source session id supplies
loop prevention without a second provenance store. A caller-origin session id
remains a pointer resolved from the durable session record rather than from
header prose.

That resolution happens once per event, and every surface renders from the one
result: the pane header an agent reads and the alias a human sees on Discord
present the same identity — agent primary, job role as qualifier, the
role name alone only for a session running no agent. Two surfaces
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
- Envelope shapes outside the current registry receive no compatibility parser;
  they remain ordinary human input unless their delimiters match a current
  registered shape.

## See Also

- ~/.teleclaude/docs/general/policy/message-identity-headers.md — the reserved namespace, why an agent never authors a header, and how to read one.
- docs/local/spec/session-projection.md — per-recipient output visibility and the alias grammar applied when content reflects.
- docs/local/spec/feature/agent_runtime/session-input-delivery.md — how caller-origin identity headers are composed and bound.
- docs/local/spec/feature/agent_runtime/direct-conversation-links.md — peer segment structure and cross-share delivery.
