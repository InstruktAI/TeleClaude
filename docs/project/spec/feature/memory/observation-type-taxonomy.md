---
description: 'The seven-value observation-type taxonomy used as the progressive-disclosure axis at save and query.'
visibility: 'public'
---

# Observation Type Taxonomy — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/memory.md

## What it is

Every memory observation carries a `type` tag drawn from a closed seven-value set — `preference`, `decision`, `discovery`, `gotcha`, `pattern`, `friction`, `context` — with `discovery` as the default. The taxonomy is a first-class progressive-disclosure axis: callers can narrow `telec memories list` and `telec memories search` to a single type, and the memory service applies a type filter to its result set when supplied. The taxonomy is enforced both on the memory service surface and in CLI parsing.

## Canonical fields

### Use cases

#### Default type on save

```
Given a save request omits type
When the memory service persists the observation
Then the persisted type is the literal string `discovery` (the default)
```

#### Validated type on save (memory surface)

```
Given a save request supplies a type value
When the memory service validates the request
Then the value must be a member of the closed set (preference, decision, discovery, gotcha, pattern, friction, context)
And any other value is rejected with a validation error
And on success the observation is persisted with the supplied type
```

#### Validated type on save (CLI)

```
Given a CLI invocation includes `--type <value>`
When the CLI parses the option
Then <value> is checked against the same seven-value set
And if absent from the set, the CLI prints `Invalid type '<value>'. Valid types: <sorted list>` and exits 1
And on success the value is forwarded to the save request
```

#### Type as search/list filter

```
Given a `--type <obs_type>` filter is supplied to `telec memories list` or `telec memories search`
When the request reaches the memory service
Then only observations whose type matches the filter are returned (across both the primary search path and the substring fallback)
```

### Cross-context references

- None. The taxonomy lives entirely inside the `memory` context.

## Known caveats

- **Taxonomy divergence vs. the memory domain spec.** The memory domain spec lists `{gotcha, decision, pattern, preference, relationship, fact}` — five values overlap, three are unique to this taxonomy (`discovery`, `friction`, `context`), and two are unique to the domain spec (`relationship`, `fact`). The default `discovery` does not exist in the domain-spec set. Whether to carry the extra values, retire them, or migrate existing observations to domain-spec equivalents is a memory-domain cutover decision.
- **The set is closed, not extensible.** The memory domain spec describes free-form extensibility per project conventions; this taxonomy is the opposite — callers cannot introduce a new type without a code change.
- **No type history.** Once persisted, an observation's type is immutable (there is no update path; see `observation-save`). Re-classifying an observation requires deleting and re-saving.
- **CLI validation set is duplicated from the service-side enum.** The two validation surfaces are hand-maintained mirrors; drift between them is a real risk if either is edited without the other.
- **The renderer displays type verbatim.** The context-injection table prints the raw type string; future renaming may require a presentation-layer mapping during cutover.
