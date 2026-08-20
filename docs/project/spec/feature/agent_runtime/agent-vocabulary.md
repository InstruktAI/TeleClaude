---
description: A supported agent has one canonical runtime identity whose launch, presentation, configuration, and setup projections stay uniform across every surface.
delivered_by:
  - agent-vocabulary-single-registry
---

# Canonical Agent Vocabulary — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md
- @docs/project/spec/domain/config.md

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
- **Presentation contract:** the display identity and palette projected to
  operator surfaces.
- **Dispatch contract:** the agent's relative position in role-specific
  selection where that runtime is eligible.

### Use cases

#### UC-AV-1: A known agent keeps one identity across runtime surfaces

```gherkin
Given an agent runtime has a canonical supported-agent entry and is enabled
When a human or agent launches, inspects, searches, or attributes a session for that runtime
Then every surface identifies the session with that agent's canonical key
And the session launches with that agent's own execution contract
And no surface silently substitutes another known agent's identity
```

#### UC-AV-2: Web presentation covers every supported agent explicitly

```gherkin
Given the canonical supported-agent vocabulary contains an enabled agent
When a human opens a web surface that lists, launches, colors, or icons agents
Then the agent appears in the generated agent list and type vocabulary
And the surface uses that agent's own presentation contract
And an exhaustive agent-specific mapping has an explicit entry for the agent
```

#### UC-AV-3: Setup recognizes every supported runtime

```gherkin
Given the canonical supported-agent vocabulary contains an enabled runtime
When an agent or operator runs installation or runner setup
Then the runtime is included in the applicable installation and prerequisite checks
And an unusable runtime is surfaced before managed work is dispatched to it
```
