---
description: Durable turn-bound conversation delivery with structured peer authorship, independent UI generations, restart-safe migration, and observable Discord identity.
---

# Conversation Delivery — Design

## Required reads

@docs/project/design/architecture/human-message-envelope.md
@~/.teleclaude/docs/software-development/policy/python/logging.md

## Purpose

Deliver local and peer conversation turns exactly under their real authorship,
preserve UI continuity across interleaving and restart, and keep presentation
text outside the authority path.

The transcript remains conversational truth. Durable accepted-turn bindings
connect ingress receipts to runtime-native transcript entries, and every
consumer advances independently from those bindings.

## Inputs/Outputs

**Inputs:**

- Durable inbound rows containing full content, source event keys, acceptance
  order, actor metadata, and acceptance time.
- Native transcript entries carrying runtime-qualified stable references.
- Active direct links and directional delivery cursors.
- Structured peer bundles accepted from local or remote transport.
- Per-adapter delivery generations and platform message receipts.

**Outputs:**

- One durable native-turn composition containing the ordered authored parts of
  each real input occurrence.
- Ordered assistant output routed to the adapter generation belonging to its
  bound turn.
- A structured peer bundle with stable bundle and segment identities, immutable
  event authorship, original source session, occurrence time, and body.
- One readable opening header and `[/TeleClaude - Peer]` closing footer per peer
  segment in the agent-facing transcript. Both delimiters are presentation,
  never parser input.
- Discord messages authored through `<Identity>[ - <raw JobRole>][ (peer)]`
  with the resolved avatar and one stable platform message across streaming
  edits. Thinking mode never appears in the Discord alias.
- Body-free structured delivery events that let agents verify production
  decisions from logs, cursors, bindings, and platform receipts.

## Invariants

### Turn provenance

- **Ingress receipt first.** A queued input and its complete receipt are
  committed before injection. Retried source events reuse the source event key
  and never create a second accepted occurrence.
- **Binding preserves composition.** Each queued receipt binds once into one
  native user entry. A native entry may contain an ordered composition of local
  human spans and receipt-backed peer or machine parts. Native terminal input
  creates its local-human composition directly from transcript truth because it
  has no adapter receipt.
- **Injected spans are known, never parsed.** The binding records the exact
  injected span for each receipt. Text before or after that known span remains a
  local-human authored part; opening headers and closing footers never establish
  boundaries or authorship. An altered or ambiguous injected span surfaces an
  input conflict rather than guessing.
- **Native references survive runtime boundaries.** A reference includes the
  runtime and native-session identity plus the runtime's stable entry, item, or
  step identity. A positional file or entry index is never durable identity.
- **Source kind and UI surface are independent.** A peer or machine turn has no
  human UI origin and never overwrites the viewing session's human-origin
  routing state. Reflection decisions read the bound turn, not
  `last_input_origin`, preview text, or another session-level summary.
- **Retention cannot create a provenance gap.** An inbound row is retained until
  its binding is durable; the binding retains the historical facts needed after
  queue cleanup.

### Output generations

- **Acceptance does not cut output.** Accepting another input never clears an
  output message ID, character offset, cursor, or pending adapter payload.
- **Transcript binding cuts the turn.** Binding the next genuine user entry
  creates the next logical generation. Output carries its bound turn identity
  and can update only that generation.
- **Adapters acknowledge independently.** Every enabled UI adapter, Discord
  admin/reflection lane, and peer-delivery consumer has its own durable cursor
  and generation receipt. No session-wide consumed bit stands in for them.
- **Late output cannot cross generations.** An older-turn snapshot never edits
  the next turn's message, even when it arrives after a later input was
  accepted.
- **Repeated wakes are idempotent.** Poller passes, agent-stop hooks, startup
  reconciliation, and duplicate transport signals can repeat without
  duplicating or reclassifying a source span.

### Peer transport and authorship

- **Structure is authoritative.** Peer detection, segment boundaries,
  loop-prevention, source identity, and Discord presentation use structured
  carrier fields. No body prefix, UUID-shaped string, timestamp, alias, or
  rendered header is scanned to recover those facts.
- **Bodies are unrestricted content.** A body may begin with or contain any
  historical or current TeleClaude header shape, including a real session UUID,
  without becoming a bridge or a new segment.
- **Readable peer blocks are visibly bounded.** The agent-facing rendering uses
  an opening header and `[/TeleClaude - Peer]` closing footer so a human can compose local text
  before and after an appended peer block. Their placement is derived from the
  durable authored-part composition; the delimiters carry no authority.
- **Event identity is immutable.** Each segment snapshots author class, agent
  runtime and historical mode, human reference and display identity, or raw
  `JobRole`, independently of later session configuration.
- **Forwarding preserves origin.** Multi-hop relay keeps the stable segment ID,
  original source session, author, occurrence time, and body. Target-specific
  echo suppression compares structured original source session IDs.
- **Cursor advance follows durable acceptance.** A source cursor advances only
  after the target atomically accepts the bundle and its structured provenance
  under the stable bundle key.

### Discord presentation and observability

- **Alias grammar is contextual.** The owning session renders its author
  without `(peer)`; any author from another session receives `(peer)`. A raw
  `JobRole` is appended as ` - <role>` before the relationship suffix.
- **Every remote author is marked.** Agents, humans, and role-bearing machine
  authors all receive `(peer)` when authored elsewhere.
- **Identity survives edits.** A Discord streaming generation is created and
  edited through the same webhook alias, avatar, thread, and message ID.
- **Webhook intent is durable.** Create intent is persisted before dispatch and
  the returned message ID before any edit. Restart reconciles a unique observed
  message when provable and never blindly resends an unresolved create.
- **Uncertainty cannot wedge the lane.** An irreducibly unresolved webhook
  create becomes a visible omitted generation after bounded reconciliation;
  later generations continue and explicit recovery may replay it.
- **Logs prove our side without leaking content.** Decision and completion
  events use policy-defined levels and structured fields for full session,
  turn, bundle, segment, generation, thread, role, relationship, alias, avatar
  selection, operation, result, and platform message IDs. Bodies, tokens, and
  PII payloads are never logged. Repeating recoverable anomalies are throttled
  or aggregated.

### Cutover and legacy state

- **Seed before delivery starts.** Startup migration records a runtime-qualified
  cutover reference and one immutable legacy generation per existing adapter
  before adapters, pollers, or conversation delivery can emit new-code output.
- **No retroactive reassignment.** Pre-cutover output stays pinned to its seeded
  generation. Binding later turns never claims or seals content already written
  there.

## Primary flows

### Accepted input and projection

1. Normalize the inbound event and atomically persist the complete queue row
   under its source event key.
2. Inject the exact stored payload without clearing any adapter generation.
3. Observe transcript truth and bind each queue row's exact injected span into
   the runtime-qualified native user entry, preserving any surrounding local
   human prefix and suffix as ordered authored parts.
4. Create one new logical turn generation from the composed native entry.
5. Route user reflection and subsequent assistant spans by that composition.
   The
   origin adapter skips its already-visible local human input; eligible admin
   lanes reflect other-source input under its real author.
6. Each consumer advances only its own cursor after durable handoff.

### Direct peer delivery

1. Project eligible bound source turns after the directional cursor.
2. Preserve inherited structured segments and create structured segments for
   local turns, assigning stable identities and immutable event authorship.
3. Suppress only segments whose structured original source equals the target.
4. Persist the pending upper bound and hand off one bundle under its stable
   bundle key.
5. Atomically accept bundle content and provenance at the target, then advance
   the source cursor.
6. Render readable headers for the agent. Discord independently renders each
   eligible segment body through its resolved alias and avatar.

### Startup and pane recovery

1. Storage migration seeds existing adapter generations and cutover references
   before request, adapter, poller, or conversation-delivery startup.
2. Reconcile queued and delivered-but-unbound input from transcript truth.
3. Resume each consumer from its own cursor and generation receipts.
4. When a pane was replaced, bind against the resumed native transcript chain;
   runtime and native-session qualification keep step identities unambiguous.
5. Reconcile pending peer bounds and Discord webhook intents without guessing
   that an external side effect did or did not occur.

## Failure modes

- A mutable session origin classifies an earlier turn according to whichever
  input arrived last, causing reflection omission or same-surface echo.
- Clearing adapter state at acceptance loses the edit target for output still
  in flight and reposts cumulative content as a new message.
- Timestamp comparison misclassifies a late snapshot from an older turn.
- Text recognition fabricates peer segments from ordinary content or freezes a
  direction forever on malformed framing.
- Flattening a composed native entry loses whether its local prefix, injected
  peer block, and local suffix were authored here or elsewhere; parsing visible
  delimiters to recover them recreates text authority.
- Looking up mutable session identity at render time rewrites historical author
  mode or fails when the source row is remote or gone.
- Purging inbound rows before binding leaves neither receipt nor transcript
  reference authoritative.
- Lazy cutover seeding lets new output enter state later claimed as legacy.
- Retiring compatibility merely because a cursor did not advance makes a frozen
  direction permanent or reintroduces echo loops.
- Blind webhook resend after a lost response duplicates a message that Discord
  already accepted; waiting forever wedges all later generations.
- Interpolated or body-bearing logs hide decision fields, leak conversation
  content, and make production behavior unverifiable.

## See Also

- docs/project/spec/session-projection.md
- docs/project/spec/session-output-routing.md
- docs/project/spec/feature/agent_runtime/direct-conversation-links.md
- docs/project/spec/feature/agent_runtime/session-input-delivery.md
- docs/project/spec/feature/agent_runtime/output-polling-and-delivery.md
- docs/project/spec/feature/agent_runtime/session-revival.md
