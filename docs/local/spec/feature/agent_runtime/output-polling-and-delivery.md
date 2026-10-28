---
description: 'agent_runtime-internal per-session polling + transcript projection that detects new agent output, dedups via digest, and delivers via adapters.'
visibility: 'public'
---

# Output Polling and Delivery — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

Output-polling-and-delivery is an agent_runtime-internal, per-session background machinery that observes a running agent's host pane and hook activity for liveness, consumes the agent CLI's native transcript file as the source of truth for content, projects new turns into structured outbound messages, and delivers them through the adapter client to subscribed adapters (Telegram, Discord, web, terminal). It is composed of three cooperating pieces inside the polling coordinator:

1. **Polling registration** — one background polling task per session, gated by an in-memory active-poller set under a coordinator lock so a session never has two concurrent pollers.
2. **Transcript-driven projection** — when the underlying pane poller signals "output changed," the coordinator reads the agent's native transcript, derives the current-turn render, and dedups against the per-session projection digest before handing off to the adapter client.
3. **Scheduled session projection** — a hook/activity wakeup pathway for all session lifecycle states. Pending-signal coalescing under a coordinator lock guarantees overlapping triggers fold into a single re-run, and a headless-only variant scopes projections to headless sessions.

Distinct from this lane: the on-demand transcript retrieval surface (which projects on request from the same transcript) and the v2 hook + render lanes (planned). v1 polling is liveness-driven push, not request-driven pull, and the host pane is treated strictly as a _signal_ — content always comes from the transcript file.

## Canonical fields

### Completed response output

The stop summary and retained final output contain every assistant-authored
text block in the completed native response, in source order. Standalone
`NOOP` entries are omitted; other text keeps its contents unchanged. A response
containing commentary followed by `NOOP` therefore retains the commentary.
Thinking and tool activity keep their separate projection categories under
`local/projects/teleclaude/spec/session-projection`.

A submitted platform wake starts a response even when it opens no authored
conversation generation. Runtime context and tool results remain within the
response they accompany. Delayed extraction stays bound to the response selected
for that stop, following `sdlc/policy/code-quality-practices`' explicit state
ownership. Silent, unavailable and empty responses retain their distinct
persistence semantics under
`local/projects/teleclaude/spec/session-output-routing`.

### Native source reading

Transcript consumers share a format-aware source view under
`sdlc/principle/design-fundamentals`. Append-only JSONL sources read newly
appended records, retaining incomplete bytes and the provider's normalization
overlap. JSON documents are parsed once per changed source version. Compressed
JSONL preserves decompression state across appends. An unchanged source reuses
its normalized view; reflection and delivery may still run when their own
state changes.

Timestamp selection uses a maintained index over normalized source order;
records sharing a timestamp or arriving with an older timestamp keep their
existing selection semantics. The index locates content and never advances a
delivery watermark.

Source identity changes, truncation and observed rewrites replace derived
reader state. The source view preserves the complete normalized entries needed
by cumulative-turn rendering, ancestry and unresolved caller bindings. Cache
eviction, session closure and restart discard only derived reading state;
native records, projection watermarks and delivery receipts retain authority.
Limited checkpoint reads keep their separate scope. These boundaries follow
`sdlc/policy/domain-ownership`.

### Use cases

#### UC-OPD4: Discord admin reflection preserves user attribution for text input

#### UC-OPD5: Discord reflection webhook failure never posts user text as the bot

#### UC-OPD6: Discord user transcription displays use user attribution or do not render

#### UC-OPD1: A person sees the procedure request without its full instructions

```gherkin
Scenario Outline: Reflect only the person's procedure request
  Given a person asks their assistant to run a published procedure with <context>
  When that request is reflected in the conversation
  Then the person sees the procedure title <addition>
  And the full procedure instructions are not shown as conversation text

  Examples:
    | context                          | addition                              |
    | additional context                | followed by the context they supplied |
    | no additional context             | alone                                 |
```

#### UC-OPD2: Command-body expansion without additional context shows only the title

#### UC-OPD3: A person sees their ordinary text unchanged

```gherkin
Given a person sends ordinary conversation text to their assistant
When that user turn is reflected in the conversation
Then the reflected text matches what the person sent
```

#### UC-OPD7: Transient tmux-binary unavailability during snapshot collection

#### UC-OPD8: Host-pane snapshot timeout during snapshot collection

#### UC-OPD9: A person can send new input without seeing the previous response reposted

```gherkin
Given a person can already see their assistant's current response
And they send new input before that response finishes updating
When the earlier response is projected again
Then its existing message is updated without reposting the visible text
And the new response begins only after the assistant receives the new input
```

#### UC-OPD10: A person can continue seeing session output after a daemon restart

```gherkin
Given a person's assistant has output being delivered to one or more adapters
When the daemon restarts or projection is woken more than once
Then each adapter continues from its own last delivered output
And already visible text is not delivered again because another adapter failed or lagged
```

#### UC-OPD11: The owning session's Discord output renders under its agent identity

#### UC-OPD12: Markdown in the owning session's output renders as formatted Discord text

#### UC-OPD13: A person keeps default daemon notices out of their conversation

```gherkin
Given a person's notification preference leaves daemon notices at its default
When a daemon notice and a genuine user turn are ready for projection in the same window
Then the notice does not appear in their conversation, whatever their role
And it does not displace or delay the user's turn
```

#### UC-OPD14: An operator sees only the Claude prompt revision the agent continued

```gherkin
Given an operator sends a Claude prompt and revises it before Claude continues
When the prompt is reflected in their Discord conversation
Then only the revision the agent continued appears as the user turn
And repeated projection or a daemon restart does not show a superseded copy
```

#### UC-OPD15: A person sees each part of a composed turn under its author

```gherkin
Given a person sends text alongside a platform-authored message in one turn
When the turn is reflected in a conversation surface
Then each visible part appears separately and in order under its own author
And a platform-only part is omitted without removing the person's text around it
```

#### UC-OPD16: Codex goal context stays outside the peer conversation

#### UC-OPD17: A person sees their input without runtime content attributed to them

```gherkin
Given a person is viewing a Codex conversation whose transcript contains their text and runtime content
When that entry is reflected
Then only positively identified human text appears under their authorship
And runtime or unknown content is not shown as theirs
And missing or malformed annotations do not erase ordinary human text
And peer and platform-authored parts keep their own authorship
```

#### UC-OPD18: An observing agent retains the last substantive session output

```gherkin
Given an agent monitoring a person's session can read its last substantive output
When that session later completes a silent turn
Then the monitoring agent still reads the same last substantive output
And the silent turn neither replaces it with empty content nor delivers it again as new output
```

#### UC-OPD19: Tmux binary momentarily not found when starting snapshot collection

### Cross-context references

- **integration** — the adapter client's send-output-update and broadcast-user-input paths deliver the projected messages to adapter-bound subscribers (Telegram, Discord, web, terminal). Adapter-side fanout, edit-vs-append semantics, rendering, actor-attributed Discord reflection, and chunking are integration's concern. agent_runtime hands over a fully rendered (message, delivery timestamp, multi-message flag) triple and lets integration decide how it lands (`local/projects/teleclaude/spec/session-output-routing`).
- **session_mirrors** — consumes the SAME native transcript as agent_runtime, but at session-end (eternal extract) rather than per-turn. Same source, different consumer; no shared state. session_mirrors must not assume agent_runtime has projected every turn — only that the transcript file is complete at end.

- **direct-conversation-links** — owns which transcript segments are eligible to cross a peer link; this poller projects the transcript-derived content that its owner makes visible.

- **identity** — identity envelopes carry immutable event authorship used by reflection. The mutable last-input-origin field remains a live reply-routing summary for unwrapped human prompts and never classifies transcript history.

- **config** — the configured output cadence (default 1.0s) drives the pane-poller cadence floor; the metrics summary interval (30s) is a coordinator-internal constant. Polling-related knobs live in the configuration's polling section.

## Known caveats

- **Response pinning needs a readable native reference.** If initial stop
  extraction finds no readable response-start entry or no usable native identity,
  delayed extraction selects the latest readable response.
- **Derived reading state retains history.** Initial reads and eviction recovery
  still parse the source needed by existing ancestry and receipt contracts.
  The source-byte budget scales with host memory up to its cap; source count is
  bounded separately. These bounds do not measure actual Python heap size;
  one oversized source remains eligible for reuse. Failed reads release their
  registered view and remain retryable. Working sets beyond the budget can
  cause rebuilds; evictions are observable. Returned entry records are read-only
  shared source data.
- **JSONL append reading trusts an immutable prefix.** Identity, truncation and
  boundary checks detect observed replacement, not every possible in-place
  rewrite that also grows a file. A valid final object without a newline is
  exposed provisionally; later growth rebuilds that view. Incomplete bytes stay
  retryable. These native-format limits follow `sdlc/policy/backward-compatibility-hygiene`.
- **Host pane is liveness, transcript is truth.** The output payload reported by the pane poller is intentionally discarded — never used as content. All delivered content comes from the native transcript's normalized source view via the start-of-turn anchor. Don't add code that forwards pane-poller output to the adapter.
- **Cumulative-turn projection, not incremental.** Each tick renders the _entire_ current turn from the start-of-turn anchor forward. Adapters use the digest to decide whether to edit, and integration handles append-vs-edit semantics. The coordinator does not produce diffs.
- **`last-message-sent-at` is mixed-purpose.** The projection watermark deliberately uses `last-projected-at` instead, because `last-message-sent-at` is touched by multiple writers and would cause projection skips or re-broadcasts. Don't conflate them.
- **Transcript discovery retries until source truth exists.** If the transcript file has not landed yet, the session remains eligible for later poller or hook-triggered discovery. Once the entry exists, its segmentation is complete from that entry alone.
- **Transient snapshot failures skip one cadence tick.** A missing tmux executable or snapshot timeout is retried on the next cadence without a user-facing error or false session-death transition. A vanished host pane stops polling without background healing; recovery is demand-driven by subsequent caller actions. Other terminal failures remain explicit.
- **Scheduled projection coalesces N signals into <=1 re-run.** If 10 events arrive while a projection is running, exactly one extra pass executes when it finishes — not 10. Callers that need every signal observed individually must not use scheduled projection as an event log.
- **Polling stops, the file remains.** When the host pane survives but the agent process exits cleanly, polling stops, the session is NOT terminated, and the transcript stays on disk for downloads. The next subscriber action drives recovery.

- **Durable generation replay.** Restart resumes each adapter from the bound turn's durable generation and platform receipts. Transcript content may be re-read, but an acknowledged source span is not recreated and an unresolved external create follows its explicit reconciliation state.

- **Output cadence governs both host-pane polling and scheduled projection wakeups.** The pane poller wakes at most every min(1.0, configured cadence) seconds; scheduled projection also uses the configured cadence as a per-session floor between projection starts. Digest dedup still decides whether a wakeup produces outbound adapter work.
- **Metrics state survives only inside the polling task.** Metrics state is keyed by session id; restart loses the running averages but emits a final summary before clearing on task teardown.
