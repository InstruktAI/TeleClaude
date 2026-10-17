---
description: 'The closed observation-type taxonomy used as the progressive-disclosure axis at save and query.'
visibility: 'public'
---

# Observation Type Taxonomy — Spec

## What it is

Every memory observation carries a `type` tag drawn from a closed set. Memories about a person: `preference`, `friction`, `context`. Business items collected as prospects (`local/projects/teleclaude/spec/feature/memory/memory-curation`), which are records in the memory store but never memories: `request` (something wanted that does not exist), `complaint`, `sentiment`, `competitor` (a mention of an alternative), with confusion recorded as `friction`. Older observations may also carry `decision`, `discovery`, `gotcha` or `pattern`, which remain valid values; `discovery` stays the default when a save names no type. The taxonomy is a first-class progressive-disclosure axis: callers can narrow `telec memories list` and `telec memories search` to a single type, and the memory service applies a type filter to its result set when supplied. The taxonomy is enforced both on the memory service surface and in CLI parsing.

## Canonical fields

### Cross-context references

- None. The taxonomy lives entirely inside the `memory` context.

## Known caveats

- **Taxonomy divergence vs. the memory domain spec.** The memory domain spec lists `{gotcha, decision, pattern, preference, relationship, fact}` — five values overlap, three are unique to this taxonomy (`discovery`, `friction`, `context`), and two are unique to the domain spec (`relationship`, `fact`). The default `discovery` does not exist in the domain-spec set. Whether to carry the extra values, retire them, or migrate existing observations to domain-spec equivalents is a memory-domain cutover decision.
- **The set is closed, not extensible.** The memory domain spec describes free-form extensibility per project conventions; this taxonomy is the opposite — callers cannot introduce a new type without a code change.

- **No type history.** Once persisted, an observation's type is immutable: curation changes a memory's statement, never its type (`local/projects/teleclaude/spec/feature/memory/memory-curation`). Re-classifying an observation requires retiring it and adding a new one.

- **The renderer displays type verbatim.** The context-injection table prints the raw type string; future renaming may require a presentation-layer mapping during cutover.
