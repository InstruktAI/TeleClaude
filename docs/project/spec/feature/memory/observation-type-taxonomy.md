---
id: 'project/spec/feature/memory/observation-type-taxonomy'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'The seven-value v1 observation-type taxonomy used as the progressive-disclosure axis at save and query.'
---

# Observation Type Taxonomy — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/memory.md

## What it is

Every memory observation carries a `type` tag. v1 fixes the type to one of seven categorical values — `preference`, `decision`, `discovery`, `gotcha`, `pattern`, `friction`, `context` — with `discovery` as the default. The taxonomy is a first-class progressive-disclosure axis: callers can narrow `telec memories list` and `telec memories search` to a single type, and `MemorySearch.search` appends `AND type = :obs_type` to its FTS5 and LIKE branches when supplied. The taxonomy is enforced by the `ObservationType` enum (Pydantic-validated on the HTTP API and validated in CLI parsing).

## Canonical fields

### Use cases

#### Default type on save

```
Given a save request omits `type`
When `MemoryStore.save_observation` constructs the row
Then the persisted `type` column is the string `discovery` (the v1 default)
```

#### Validated type on save (HTTP)

```
Given an HTTP `POST /api/memory/save` body contains `type: <value>`
When FastAPI binds the request to `SaveObservationRequest`
Then `<value>` must be a member of `ObservationType` (one of: `preference`, `decision`, `discovery`, `gotcha`, `pattern`, `friction`, `context`)
And any other value yields HTTP 422
And on success the row is persisted with `type = <value>`
```

#### Validated type on save (CLI)

```
Given a CLI invocation includes `--type <value>`
When the CLI parses the option
Then `<value>` is checked against `_VALID_OBS_TYPES` (the same seven-value set)
And if absent from the set, the CLI prints `Invalid type '<value>'. Valid types: <sorted list>` and exits 1
And on success the value is forwarded to the HTTP body
```

#### Type as search/list filter

```
Given a `--type <obs_type>` filter is supplied to `telec memories list` or `telec memories search`
When the request reaches `MemorySearch.search` (either FTS5 branch or LIKE fallback)
Then `AND type = :obs_type` is appended to the WHERE clause
And only rows whose `type` column matches the filter are returned
```

### Implementation pointers (v1)

- Enum definition — `teleclaude/memory/types.py:13` (`ObservationType`)
- Save default (`ObservationInput.type = ObservationType.DISCOVERY`) — `teleclaude/memory/types.py:43`
- HTTP request default (`SaveObservationRequest.type = ObservationType.DISCOVERY`) — `teleclaude/memory/api_routes.py:26`
- CLI validator (`_VALID_OBS_TYPES`) — `teleclaude/cli/telec/handlers/memories.py:20`
- CLI parser — `teleclaude/cli/telec/handlers/memories.py:37` (`_parse_observation_type`)
- Server-side type filter wiring — `teleclaude/memory/search.py:91` (FTS5 branch) and `teleclaude/memory/search.py:116` (LIKE branch)
- Persisted column — `teleclaude/core/db_models.py:164` (`type: str` on `MemoryObservation`)

### Cross-context references

- None. The taxonomy lives entirely inside the `memory` context.

## Known caveats

- **v1 ↔ v2 taxonomy divergence.** v2's domain spec lists `{gotcha, decision, pattern, preference, relationship, fact}` — five values overlap, three values are v1-only (`discovery`, `friction`, `context`), and two are v2-only (`relationship`, `fact`). The v1 default `discovery` does not exist in the v2 set. v2 cutover must decide whether to carry the v1-only values, retire them, or migrate existing rows to v2 equivalents.
- **The enum is closed, not extensible.** The v2 domain spec says "Free-form extensible per project conventions" — v1 is the opposite: callers cannot introduce a new type without a code change.
- **No type history.** Once persisted, an observation's `type` is immutable in v1 (there is no update path; see `observation-save`). Re-classifying an observation requires deleting and re-saving.
- **The CLI validation set is duplicated from the enum.** `_VALID_OBS_TYPES` in `memories.py` is a hand-maintained `set[str]` mirror of `ObservationType`. Drift between the two is a real risk if either is edited without the other; reviewers should keep them in sync.
- **The renderer displays `type` verbatim.** The context-injection table prints the raw enum string. v2's renaming may require a presentation-layer mapping if old rows are still in flight during cutover.
