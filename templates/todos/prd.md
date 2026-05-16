# PRD: {slug}

<!--
=============================================================================
PRD TEMPLATE — BMAD-aligned. This is the canonical PRD structure for the
prepare lifecycle. Both intake (writer) and PRD review (reviewer) read this
file as the rubric. If you change the structure here, the reviewer's rubric
changes automatically — single source of truth.

WHAT BELONGS IN A PRD: what the user wants and why. Observable outcomes.
Hard constraints. Risks. Open questions the human must answer.

WHAT DOES NOT BELONG IN A PRD (leakage — reviewer will reject):
- Specific file paths, directory paths, module paths.
- Specific class names, function names, type names, event names.
- Specific database columns, table names, config keys, YAML field names.
- Specific package layouts, stream names, queue names.
- Function signatures, protocol shapes, interface contracts.
- Implementation patterns ("use Redis Streams", "build a Pydantic model"),
  unless the choice is a hard external constraint (not an internal one).
- Counts, thresholds, or numeric defaults that are tuning knobs, not
  user-facing contracts.

If a constraint genuinely narrows the solution space without prescribing
implementation (e.g. "must integrate with the existing identity model" or
"must not break the existing UI fanout"), that goes in Constraints. If a
detail would foreclose valid alternatives the architecture phase should be
free to choose between, it does not go in the PRD.

The discriminator: could the builder satisfy this criterion via a different
implementation? If yes, the PRD is silent on the implementation. If no
because of a real external constraint, name the constraint.
=============================================================================
-->

## Goal

<!--
JTBD-framed. One or two sentences. The shape:

  "The user wants the system to do X, for Y, under conditions Z."

X = the capability delivered. Y = the beneficiary or use case. Z = the
conditions or qualifiers that bound the goal.

Bad: "Refactor notification dispatch to be more robust."
Good: "The user wants the system to reliably deliver human-targeted
notifications to their preferred channel, with automatic fallback, so that
operational events that need attention always reach a human."
-->

-

## Why

<!--
The underlying need behind the surface ask. If the stated request is a
proxy for something deeper, surface the root cause here (5 Whys applied
silently — output the answer, not the ladder).

If the work fixes broken behavior, name what is broken and what the broken
behavior costs in user-observable terms (not implementation terms).

Bad: "The push-callback chain swallows exceptions and the placeholder
wrappers send useless bodies."
Good: "Today, recipients see meaningless 'Notification #N created' messages
and never learn when delivery silently fails. A single channel outage means
a missed alert with no observable trace. Operators cannot tell what got
stuck."
-->

-

## Affected actors

<!--
Who is impacted. Roles, not individuals. Include downstream systems and
integrating services if the change crosses a contract boundary.
-->

-

## Scope (MoSCoW)

<!--
Force every surfaced item into one of these four buckets with a brief
reason. Items in Won't are explicit deferrals — name them so the reviewer
can confirm they are out of scope on purpose, not by oversight.

Express each item in user-observable language. "Operator can query stuck
dispatches" is in scope; "implement an inspection CLI handler" is HOW.
-->

### Must

-

### Should

-

### Could

-

### Won't (this todo)

-

## Success criteria

<!--
Observable indicators that the work succeeded. Express in Gherkin form
where behavior is testable:

  Given <context>
  When <event>
  Then <observable outcome>

The outcome must be observable from outside the system — a user sees X, an
operator can query Y, a downstream consumer receives Z. Do not name
internal state, internal tables, or internal types here.

Bad: "Given a notification with level >= threshold, when the cartridge
emits, then a dispatch_state row is created with state=pending."
Good: "Given a notification meets the human-dispatch threshold, when it is
produced, then every resolved recipient eventually receives delivery on
one of their configured channels or appears in the operator's unreachable
list."
-->

- Given …, when …, then …

## Constraints

<!--
Hard limits the solution must respect. External constraints, not internal
preferences.

Examples that belong here:
- Must not break the existing UI fanout consumed by the WebSocket projection.
- Must not change the contract of the leaf send functions.
- Must respect the existing identity model (PersonEntry roles).
- Must preserve at-least-once semantics relied on by downstream consumers.

Examples that do NOT belong here (those are architecture):
- Must use Redis Streams with consumer groups.
- Must live in `teleclaude/notifications/`.
- Must register a new event type called `notification.deliver.requested`.
-->

-

## Risks and unknowns

<!--
Light pre-mortem. Imagine the work shipped and failed — what would have
gone wrong? List failure modes the human or the architect needs to think
about. Risks that only the user can resolve (business risk, scope risk,
political risk) go here too.

Each risk is one sentence. No mitigation plan in this section — that
belongs in architecture or plan.
-->

-

## Brownfield context

<!--
If the work touches existing code, briefly note what's there. Flag
brownfield vs greenfield. Name the modules or surfaces involved at a
domain level (not file paths). Full code-grounded analysis happens in the
architecture phase — the PRD just orients the reader.

Bad: "Replace `teleclaude/events/cartridges/notification.py:_invoke_push_
callbacks` and the wrappers under `teleclaude/events/delivery/`."
Good: "The current notification delivery path spans the event projection
cartridge, per-channel placeholder wrappers, and daemon-startup callback
wiring. The leaf send functions are sound and reused as-is."
-->

-

## Open questions

<!--
Anything the human owner needs to decide before architecture begins. If a
question is one the architect can resolve from codebase + defaults, do not
put it here — let the architect resolve it. This section is for genuine
human-judgement decisions.
-->

-
