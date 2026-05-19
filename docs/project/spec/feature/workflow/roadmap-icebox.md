---
id: 'project/spec/feature/workflow/roadmap-icebox'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Frozen-but-recoverable state for roadmap entries that are not being actively pursued; iceboxed entries do not participate in dependency-driven dispatch; unfreeze restores them to active without losing artifacts or edges.'
---

# Roadmap Icebox — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

The icebox is the parking lot for roadmap entries the project does not want to lose but does not want to act on. Freezing a roadmap entry flips its status from `active` to `icebox`; all of its associated state — todo state JSON, artifacts, dependency edges, position — remains in `todos.db` untouched. Iceboxed entries are excluded from the default `telec roadmap list` view and, more importantly, are excluded from the prepare and work orchestrators' candidate search, so they neither block nor satisfy dependencies of active entries.

Unfreezing is the inverse: it flips the status back to `active`, returning the entry to the live roadmap and to the orchestrators' attention. Because no row was deleted and no edge was severed, the entry resumes with all of its history intact.

The icebox is distinct from `remove` — remove deletes the roadmap row, while freeze preserves it. The `telec roadmap migrate-icebox` command exists for backwards compatibility but is a no-op under v1 because icebox data lives entirely in `todos.db`; there is no on-disk `todos/_icebox/` tree to migrate from anymore.

## Canonical fields

### Use cases

```
Given an active roadmap entry "deferred-feature"
When the operator runs "telec roadmap freeze deferred-feature"
Then the entry's status changes to "icebox"
And the entry is no longer returned by "telec roadmap list" (the default view)
And the entry's todo_state, artifacts, and roadmap_deps rows are preserved unchanged
And the _on_mutation("todo_updated") hook fires so cached views refresh
```

```
Given an iceboxed entry "deferred-feature"
When the operator runs "telec roadmap list --include-icebox"
Then "deferred-feature" appears in the listing
And its rendered status is "icebox"
```

```
Given an iceboxed entry "deferred-feature"
When the operator runs "telec roadmap list --icebox-only"
Then only entries with status="icebox" are shown
And active and delivered entries are hidden regardless of other flags
```

```
Given an iceboxed entry "deferred-feature"
When the operator runs "telec roadmap unfreeze deferred-feature"
Then the entry's status flips back to "active"
And it reappears in the default "telec roadmap list" view
And its dependency edges and artifacts remain intact
And the next prepare/work pickup may consider it again
```

```
Given an active entry "alpha" depending on iceboxed entry "beta"
When the work orchestrator searches for the next runnable slug
Then "alpha" is skipped because "beta" is neither delivered nor active
And the resolver reports the candidate as dependency-blocked
And the iceboxed "beta" is not itself dispatched, regardless of its own readiness
```

```
Given the operator runs "telec roadmap freeze missing-slug" for a slug that is not in the roadmap
When the freeze handler resolves the active entry
Then no row is mutated
And the command prints "Slug not found in roadmap: missing-slug" and exits non-zero
```

```
Given a legacy project that pre-dates the todos.db migration
When the operator runs "telec roadmap migrate-icebox"
Then the command prints a no-op message acknowledging that icebox data already lives in todos.db
And exits successfully without touching the filesystem or the database
```

### Implementation pointers (v1)

- `teleclaude/cli/telec/handlers/roadmap.py:395` — `_handle_roadmap_freeze` argument parsing and freeze dispatch
- `teleclaude/cli/telec/handlers/roadmap.py:433` — `_handle_roadmap_unfreeze` argument parsing and unfreeze dispatch
- `teleclaude/cli/telec/handlers/roadmap.py:471` — `_handle_roadmap_migrate_icebox` deprecated no-op
- `teleclaude/cli/telec/handlers/roadmap.py:67` — `_handle_roadmap_show` honors `--include-icebox` / `--icebox-only` filters
- `teleclaude/core/todos_db/_roadmap.py:297` — `freeze` flips status to `"icebox"` and stamps `updated_at`
- `teleclaude/core/todos_db/_roadmap.py:310` — `unfreeze` flips an icebox entry back to `"active"`
- `teleclaude/core/todos_db/_roadmap.py:79` — `_list_roadmap_models` builds the `allowed` status set from the visibility flags
- `teleclaude/core/todos_db/schema.sql:18` — partial unique index keeps `(active, icebox)` slug-unique so reuse is impossible while frozen
- `teleclaude/core/next_machine/slug_resolution.py:285` — `resolve_next_work_queue_db` iterates only `list_roadmap()` (active entries by default), so icebox entries are silently excluded from candidate search

### Cross-context references

- `agent_runtime` / daemon cache — `freeze` and `unfreeze` invoke `_on_mutation("todo_updated")` which invalidates the daemon's cache and pushes a refresh to TUI / frontend subscribers
- `workflow` orchestration internals — the prepare/work resolvers in `next_machine` consume the active roadmap projection; iceboxed entries are out of band by virtue of being filtered upstream

## Known caveats

- Freezing keeps the todo recoverable — fundamentally different from `remove`, which deletes the roadmap row and its dep edges.
- Iceboxed entries retain artifacts, lifecycle state, and dependency edges. The edges remain in `roadmap_deps` but never gate dispatch while the source slug is iceboxed.
- An active entry that depends on an iceboxed entry is blocked: the dependency is unsatisfied (iceboxed is not delivered). To unblock, the operator either unfreezes the dep, delivers it, or rewrites the dep edge with `telec roadmap deps`.
- `telec roadmap migrate-icebox` is a backwards-compatibility no-op. The icebox is fully DB-resident under v1; there is no `todos/_icebox/<slug>/` filesystem tree to migrate.
- Slug uniqueness still applies across `active` and `icebox`: an iceboxed slug cannot be re-added until it is unfrozen, removed, or delivered.
