---
description: Agent-facing briefs and provenance claims use explicit dispatch involvement rather than inferred human participation.
delivered_by:
  - human-involvement-propagates-at-dispatch
---

# Involvement-Aware Briefing — Spec

## Required reads

@docs/project/spec/domain/context.md

## What it is

The context-selection contract for telling a spawned agent whether a human
participated in its dispatch. Agent-facing briefs use that declaration when
describing who supplied scope or instructions, without promoting lineage or
caller identity into participation evidence.

## Canonical fields

### Use cases

#### UC-IAB1: Agent-owned dispatch stays agent-owned

```gherkin
Given an agent dispatches a child with human involvement declared false
And the dispatching agent selected the child's scope
When the child describes or evaluates that scope
Then it identifies the scope as agent-supplied rather than human-supplied
And it does not require a human to restate the scope merely because the child and dispatcher disagree
```

#### UC-IAB2: Human participation is stated only when declared

```gherkin
Given a spawned agent receives explicit dispatch-involvement context
When its brief or verdict attributes the instructions it received
Then it claims human participation only when the declaration is true
And it never derives participation from lineage, sender identity, or a parent session
```

### Cross-context references

- **agent_runtime** transports the dispatch declaration into the child session.
- **workflow** and review commands consume the resulting context when framing
  lifecycle work, review targets, corrections, and escalations.

## See Also

- ~/.teleclaude/docs/general/policy/human-involvement-recording.md
