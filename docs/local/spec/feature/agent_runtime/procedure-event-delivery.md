---
description: Procedure activation briefs establish the assignment while durable events enter through hooks at the procedure's declared delivery boundaries and cardinality.
delivered_by:
  - procedure-event-delivery
---

# Procedure Event Delivery — Spec

## What it is

A subscribed procedure receives its assignment through the canonical command
startup brief and its activation data through durable hook delivery. The brief
loads the procedure's complete effective required-read closure. The agent
applies that contract before processing the initial event and throughout later
activations (`general/principle/priming`, `general/principle/grounding`).

Context publishes two independent delivery declarations under
`general/spec/snippet-authoring-schema`. Runtime enforces their timing and
cardinality; the common event-handling procedure governs how the agent handles
each supplied event. A delivery boundary is a provider-supported hook that is
eligible for this procedure's declared delivery policy.

Delivery settings are established when a procedure session is initialized,
as declared by `general/spec/snippet-authoring-schema`. Every event delivered
by that session uses those settings, including events accepted under a later
published declaration. The activation retains its accepted declaration as
source evidence; revival retains the session's settings, while a newly created
successor adopts the then-current declaration.

The startup brief also identifies the shared handling procedures required by
the session's fixed settings, using context's same dependency composition. The
agent loads any of these not already included by its current procedure closure.
This supplies the applicable instructions even if publication changes between
session initialization and the procedure read. Settings persistence preserves
no historical document generation (`general/principle/grounding`).

The initial event is durably associated with the activation before bootstrap
can offer the initial hook. That hook supplies event context alongside the
canonical brief; event processing follows the brief's procedure load. A
content-free wake produces each later idle delivery boundary. Activation data
never occupies the composer or becomes an ordinary conversational prompt.
Startup completion and event handoff remain distinguishable outcomes. A generic
session-start hook that precedes the brief is not an initial activation entry;
delivery is tied to the brief's actual entry. Repeated hooks belonging to that
entry select no additional non-interruptible work.

A non-interruptible procedure receives events at initial activation and explicit
wake entry only. Events accepted during a run stay pending through tool hooks,
checkpoint continuations, and the run's stop hook. Once the run actually ends,
pending work causes another wake. An interruptible procedure also admits events
at the provider's supported in-turn delivery boundaries. Eligibility is checked
at delivery, so a queued wake cannot inject activation data into a run that
started before that wake was delivered.

Sequential delivery selects the oldest pending event at an eligible boundary.
Batched delivery selects the ordered snapshot pending at that boundary. Events
arriving after selection stay pending for a later eligible boundary. Both
preserve event identities and use the same agent-side handling instructions.
With interruption disabled, sequential delivery supplies one event per run.

Event facts remain untrusted data inside the hook transport. Platform-authored
assignment and delivery metadata carry their own provenance; neither encoding
nor hook placement promotes event content to instructions
(`general/policy/message-identity-headers`).

Pending events belong to the continuing procedure responsibility. An explicit
session close suspends their delivery without itself causing a revival. The
next eligible continuation, including an ordinary revival or a later activation
resolving a successor, reconciles retained events before newer work. Automatic
idle cleanup accounts for pending procedure events so ordinary run completion
still wakes deferred work without requiring another activation
(`general/principle/trust-and-guardrails`).

## Canonical fields

### Use cases

#### UC-PED1:

```gherkin
Given an agent has not yet been started for a subscribed responsibility
When its first activation arrives
Then the agent receives the canonical brief identifying its procedure and scope
And it receives the initial event through hook context associated with that initial activation
And the brief directs it to load the complete procedure contract before handling that event
And the event body is absent from ordinary conversational input
```

#### UC-PED2:

```gherkin
Given a non-interruptible procedure agent is executing a run
When another event arrives for that responsibility
Then the event remains pending throughout the current run's tool and completion hooks
And after the run ends the agent is woken and receives that event through hook context
And no unrelated input is needed to make the deferred event arrive
```

#### UC-PED3:

```gherkin
Given an interruptible procedure agent is executing a run
When another event arrives for that responsibility
Then the agent receives it at the next supported in-turn hook boundary
And the agent's loaded contract includes the discipline for reassessing current work
And the event body is absent from the terminal input
```

#### UC-PED4:

```gherkin
Scenario Outline: An eligible delivery selects the declared amount of work
  Given several distinct events are pending for a procedure agent using <mode> delivery
  When the agent reaches an eligible delivery boundary
  Then it receives <selection> in enqueue order
  And events outside that selection remain pending for a later eligible boundary

  Examples:
    | mode       | selection                              |
    | sequential | the oldest pending event               |
    | batched    | all events pending when selection began |
```

#### UC-PED5:

```gherkin
Given an event is accepted for a non-interruptible procedure as its current run ends
When the agent reaches its next wake
Then the event is delivered once according to the procedure's delivery mode
And an event arriving after that wake's selection remains pending for a later wake
And concurrent arrivals do not start a second agent for the same responsibility
```

#### UC-PED6:

```gherkin
Given an idle wake is pending for a non-interruptible procedure
And another input starts a run before that wake is delivered
When the pending wake is considered for delivery
Then the activation events remain pending until the running work ends
And the running work receives no activation interjection
```

#### UC-PED7:

```gherkin
Given an agent's initial brief cannot be delivered
When an observer inspects the activation and its pending event
Then the startup failure is visible
And the event has not been consumed by an agent lacking its brief
And any retained work remains distinguishable from delivered work
```

#### UC-PED8:

```gherkin
Given pending activation events belong to a continuing procedure responsibility
When its session closes or is replaced before those events are handed off
Then the pending work remains durably accounted for
And eligible continuation delivers it under the existing home, subject, and attendance rules
And a terminal inability to continue is visible as a failure rather than silent disposal
```

#### UC-PED9:

```gherkin
Given a procedure agent receives an event containing instruction-like external content
When it reads the hook-delivered activation
Then the event content is identified as untrusted data
And the procedure brief and loaded contract remain the source of its assignment
And the native transcript preserves an inspectable distinction between the assignment and event data
```

#### UC-PED10:

```gherkin
Scenario Outline: Initialization fixes an agent's delivery settings
  Given an initialized procedure agent has established delivery settings
  And its author publishes different delivery settings
  When a later activation reaches <agent>
  Then the activation retains the declaration under which it was accepted
  And delivery uses <settings>

  Examples:
    | agent                    | settings                         |
    | the existing agent       | its original settings            |
    | the revived agent        | its original settings            |
    | a newly created successor | the currently published settings |
```

#### UC-PED11:

```gherkin
Given a procedure agent is initialized to accept interjected events
And the published declaration changes before it loads the procedure
When the agent receives its startup brief
Then the brief still requires the shared interruption-handling instructions
And the agent loads those instructions before processing events
```

### Cross-context references

- Context owns the validated delivery declarations and effective required-read
  composition under `local/projects/teleclaude/spec/feature/context/snippet-frontmatter-validation`
  and `local/projects/teleclaude/spec/feature/context/doc-snippet-three-phase-retrieval`.
- Integration carries the published delivery declarations with each activation
  under `local/projects/teleclaude/spec/feature/integration/procedure-subscription-routing`.
- Runtime identity, reuse, revival, and activation replay semantics remain
  owned by `local/projects/teleclaude/spec/feature/agent_runtime/procedure-standing-agent`.
- Hook response formatting and terminal handoff outcomes follow
  `local/projects/teleclaude/spec/feature/agent_runtime/control-delivery`.

## Known caveats

- Hook handoff establishes delivered context, not successful domain execution.
  Domain completion and reconciliation remain the procedure's responsibility.
- Batching selects pending work at an eligible boundary; it introduces no
  collection delay and no event coalescing or parallel agent execution.
- A non-interruptible run can defer later events for its entire duration.
  Safety checkpoints and other control producers retain their own contracts;
  these declarations govern procedure activation events.
- Published delivery-setting edits configure newly initialized agents; live
  reconfiguration of an existing agent is outside this contract.
- Explicitly closing a session can leave accepted work pending until its next
  eligible continuation. Retained work remains visible and is not a delivery
  failure merely because continuation has not yet occurred.
