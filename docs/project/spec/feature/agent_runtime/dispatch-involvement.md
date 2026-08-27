---
description: Explicit human-involvement context carried unchanged through every agent-session dispatch.
delivered_by:
  - human-involvement-propagates-at-dispatch
---

# Dispatch Involvement — Spec

## Required reads

@docs/project/spec/domain/agent_runtime.md

## What it is

The agent-runtime contract for carrying a dispatcher's declaration of whether a
human participated in the operation that creates a child session. The
declaration describes the dispatch act only; session lineage and caller identity
remain separate facts.

## Canonical fields

- Caller-facing declaration: the existing `--human-involved` flag. Spawn
  surfaces reuse it and introduce no second involvement mechanism.
- Existing context carrier: session `additional_context` with
  `human_in_loop: true | false`. The CLI maps `--human-involved` to `true` and
  omission to `false`; agents do not need a second declaration mechanism.
- Formatter-governed workflow dispatches omit `--human-involved` and therefore
  enter their child sessions as not human-involved. An agent uses the flag only
  for an exceptional non-workflow launch in which a human genuinely participates.

### Use cases

#### UC-DI1: A dispatch declaration reaches the child unchanged

```gherkin
Given an agent declares whether a human participated in a child-session dispatch
When any supported agent-session spawning surface creates the child
Then the child receives that same declaration in its startup context
And lineage, sender identity, and the existence of a parent session do not alter it
```

#### UC-DI2: An omitted declaration is not involved

```gherkin
Given an agent-session spawning request carries no human-involvement declaration
When the child session starts
Then the dispatch is treated as not human-involved
And any initial prompt supplied to the child carries `human_in_loop: false`
And the child does not infer human participation from any other session fact
```

#### UC-DI4: Generic dispatch context remains intact

```gherkin
Given an agent supplies generic context alongside its human-involvement declaration
When a supported agent-session spawning surface creates the child
Then the child receives the generic context unchanged
And the human-involvement declaration remains available independently
```

### Cross-context references

- **context** consumes the declaration when composing agent-facing startup
  context and briefing provenance.
- **workflow** supplies the declaration on lifecycle-owned dispatch requests;
  it does not derive the value from todo lineage or creation metadata.

## See Also

- ~/.teleclaude/docs/general/policy/human-involvement-recording.md
