---
description: Caller-only observations of missing native startup or in-turn activity,
  preserving runtime status and agent-owned assessment.
visibility: internal
---

# Supervisory Silence Observations — Spec

## What it is

A supervising agent receives bounded evidence when a child it is waiting on
has not produced an expected native signal. The observation reports the
absence of that signal and supplies terminal evidence for the caller's
assessment. The target retains its evidenced runtime activity state.

The assessment boundary follows `general/principle/intelligence-boundaries`
and `general/procedure/ai-to-ai-operations`. Intelligence interprets pane
evidence and owns recovery; elapsed silence supplies no provider-failure
diagnosis. Native failures, approval waits and input-delivery outcomes retain
their existing owners.

## Canonical fields

### Observation facts

The observation identifies the child and its runtime, the owning run or turn,
the missing signal, its observation time and the applicable window. It carries
bounded pane evidence when available and an actionable inspection reference
with an explicit evidence gap when the pane is unavailable.

`AGENT_NO_START_TIMEOUT_S` owns the startup window. It applies to a supervised
launch with accepted initial work whose native activity remains unknown. An
empty launch awaiting the caller's first instruction has no startup work
expectation.

`AGENT_NO_SIGNAL_TIMEOUT_S` owns the active-turn window. The clock is the
latest recorded normalized activity or activity-state entry. The existing
native-event bookkeeping excludes a turn while any reported tool-call
identifier remains open. The platform classifies no tool contents, provider
prose or terminal contents to infer an anomaly.

### Supervising callers

The subscriptions owner resolves a current persistent caller distinct from the
child. An eligible caller is an open managed agent session with an execution
surface. A one-reply subscription alone establishes no supervisory interest.
Historical initiator identity alone establishes no current interest.

Local and remote relationships share the subscription lifecycle. An undetached
dispatch records supervision; an explicit later persistent subscription can
establish it independently. Unsubscribe revokes it. An active direct
conversation does not suppress a silence observation.

The observation enters the caller through agent control delivery. Durable
acceptance does not prove the caller processed it. An unavailable caller or a
failed delivery is recorded without redirecting the observation to the child
or a human channel. A session with no eligible caller produces no silence
notification or silence-derived activity-state transition.

### Frequency and recovery

One observation is claimed per owning run or turn. A fresh run or real prompt
opens its next opportunity. Ordinary tool activity advances the activity clock
but does not create additional notices within the same turn. An atomic claim
rechecks the current evidence, so newer native activity invalidates an earlier
silence view.

Daemon replacement preserves the claim and supervision relationship. It
creates no new observation window and replays no inferred-failure notice into
a human channel.

Retained failure states caused only by startup or in-turn silence are brought
forward to unknown or active activity, respectively. Native failures retain
their state. Runtime evidence, lifecycle, tool tracking and spent claims are
preserved. An overwritten historical state-entry time is not represented as
recovered native evidence.

### Cross-computer compatibility

An unsupported destination is recorded as unavailable for
neutral delivery. An observation is never recoded as a confirmed failure to
make an older peer accept it. Capable receivers consume legacy silence
evidence as observations while legacy wire values remain accepted.

### Use cases

#### UC-SSO1: An ordinary interactive session receives no silence diagnostic

```gherkin
Scenario Outline: Ordinary activity remains as evidenced
  Given a human uses a regular interactive session with no supervising agent caller
  And its recorded activity is "<activity>"
  When the corresponding silence observation window elapses
  Then its recorded activity is unchanged
  And its human-facing conversation receives no silence notification
  And no silence assessment is submitted to that target agent

  Examples:
    | activity |
    | unknown  |
    | active   |
```

#### UC-SSO2: A supervising agent assesses missing startup activity

```gherkin
Given a supervising agent dispatched initial work to a child
And the child has reported no native activity for that run
When the startup observation window elapses
Then the supervising agent receives one observation naming the absent startup signal
And the child remains unknown
And the observation carries pane evidence or an explicit gap with an inspection reference
And the supervising agent decides whether recovery is needed
```

#### UC-SSO3: A supervising agent assesses missing in-turn activity

```gherkin
Given a supervising agent is waiting for an active child's work
And every native tool call reported by the child has closed
When the activity observation window elapses without another native signal
Then the supervising agent receives one observation naming the absent activity
And the child remains active
And the platform makes no failure diagnosis from the silence or captured text
```

#### UC-SSO4: Reported open tool calls exclude the active-turn observation

#### UC-SSO5: Only current distinct supervisors receive the observation

#### UC-SSO6: Observation claims remain bounded and current

#### UC-SSO7: A remote supervisor retains control of its subscription

#### UC-SSO8: Version skew preserves the meaning of evidence

```gherkin
Scenario Outline: A peer receives only an observation contract it supports
  Given a child satisfies a supervised silence observation condition
  And its caller's computer "<support>"
  When remote observation delivery is considered
  Then the platform performs "<outcome>"
  And the observation is never represented as a confirmed failure or human fallback

  Examples:
    | support                               | outcome                             |
    | supports neutral observations         | caller-only neutral delivery        |
    | does not support neutral observations | records unavailable remote delivery |
```

#### UC-SSO9: Retained inferred failures do not invent evidence

```gherkin
Given a human views a retained session whose failure state was inferred only from elapsed silence
When that state is brought to the supervisory observation contract
Then startup silence is represented as unknown activity and in-turn silence as active activity
And native failure records remain failures
And lifecycle, native activity, tool tracking and spent observations are preserved
And an overwritten historical entry time is not presented as recovered evidence
And old inferred-failure notices do not appear in the human conversation
```

### Cross-context references

- **agent_runtime** — `local/projects/teleclaude/spec/feature/agent_runtime/session-lifecycle`
  owns normalized activity and lifecycle projections.
- **subscriptions** — `local/projects/teleclaude/spec/feature/agent_runtime/session-subscriptions`
  owns caller relationships;
  `local/projects/teleclaude/spec/feature/agent_runtime/control-delivery`
  owns delivery as agent control content.
- **reconciliation** — `local/projects/teleclaude/spec/feature/reconciliation/fleet-cross-version-interop`
  owns peer capability negotiation.

## Known caveats

- Native hooks do not report every kind of model progress. Healthy reasoning
  can accompany missing signals; the observation remains evidence for caller
  assessment.
- The open-tool exclusion depends on native start and closure reports. Missing
  closure evidence remains unresolved bookkeeping, not a content-derived guess.
- One observation per run or turn does not report a second silent interval in
  that turn after activity resumes.
- A session with no supervising caller has no silence-assessment agent. This
  contract creates no replacement supervisor.
- An observation claim precedes its acceptance into control delivery. A process
  loss between those acts can leave the observation unreceived; the claim remains
  spent. Accepted control payloads retain their own recovery contract.
