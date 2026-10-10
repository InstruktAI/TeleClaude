---
description: A supported agent has one canonical runtime identity whose launch, presentation,
  configuration, and setup projections stay uniform across every surface.
---

# Canonical Agent Vocabulary — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md
- @docs/local/spec/domain/config.md

## What it is

The supported-agent vocabulary has one canonical owner in the agent-runtime
context. Each agent entry carries the identity and runtime facts needed to
launch, attribute, present, configure, and install that runtime. Consumers use
the owner's typed or generated projections; they do not redefine the set of
agent keys or silently substitute one known agent for another.

## Canonical fields

- **Agent key:** the stable identity used by configuration, sessions, history,
  hooks, APIs, and user interfaces.
- **Execution contract:** executable identity and launcher metadata used to
  start the runtime.
- **Attribution contract:** commit identity and protocol identity used when the
  runtime acts.
- **Readiness contract:** the prompt marker and other agent-specific facts used
  to decide when input can be sent.
- **Composer control contract:** the leading characters with which a submitted
  prompt starts an interface mode or command in that runtime's composer, the
  neutralizing mark that makes such a prompt ordinary and still submits it on
  one discrete Enter, and the trailing mark, if any, that makes a prompt ending
  in a backslash still submit on that Enter — all verified through the
  platform's own paste delivery, never inferred from typed keystrokes or
  another runtime.
- **Presentation contract:** the display identity and palette projected to
  operator surfaces.
- **Dispatch contract:** the agent's relative position in role-specific
  selection where that runtime is eligible.

### Compaction launch declaration

An agent's canonical compaction declaration carries its native command and the
runtime-owned recipe for a temporary launch resuming its recorded native
transcript. The recipe is an internal declaration, separate from the
operator-editable launch profiles. The ordinary desk profile keeps native
slash commands disabled; the compaction recipe enables its native command and
preserves the other applicable confinement settings, including bundled-skill
suppression.

The launch carries immutable coordination context for its maintenance attempt
to its managed hook subprocesses. It changes neither the conversation's
persisted confinement identity nor the provider's native transcript semantics.
Agents without a declared command and launch recipe retain their existing
idle-close eligibility; the declaration supplies no new provider capability.

### Use cases

#### UC-AV-1: A known agent keeps one identity across runtime surfaces

```gherkin
Given an agent runtime has a canonical supported-agent entry and is enabled
When a human or agent launches, inspects, searches, or attributes a session for that runtime
Then every surface identifies the session with that agent's canonical key
And the session launches with that agent's own execution contract
And no surface silently substitutes another known agent's identity
```

#### UC-AV-3: Setup recognizes every supported runtime

```gherkin
Given the canonical supported-agent vocabulary contains an enabled runtime
When an agent or operator runs installation or runner setup
Then the runtime is included in the applicable installation and prerequisite checks
And an unusable runtime is surfaced before managed work is dispatched to it
```
