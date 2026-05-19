---
id: 'project/spec/feature/workflow/todo-creation'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Three ways to create a Todo — empty `create` skeleton, content-bearing `dump` (with optional --draft / --prepped lanes), and design-time `design` / `co-create`. Created todos route through lifecycle notifications via the planning.todo_dumped event.'
---

# Workflow Todo Creation — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

The Todo aggregate inside the `workflow` bounded context is created through three entrypoints that map to three intents:

- **`telec todo create <slug>`** — scaffolds an empty draft skeleton: a roadmap entry plus a default `TodoState` with `kind` and `lifecycle_phase=draft`. No `input` artifact is written. Used when a human or agent wants to reserve a slug and fill content later.
- **`telec todo dump <slug> <content>`** — scaffolds the same skeleton AND attaches content as an artifact in one transaction, then emits the `domain.software-development.planning.todo_dumped` event so the lifecycle router can pick it up. Two side lanes:
  - `--draft`: same skeleton + `input` artifact, but `kind="draft"`, `lifecycle_phase="draft"`, and the event is suppressed so nothing dispatches until a human invokes.
  - `--prepped`: writes the content as the `implementation-plan` artifact (not `input`), stamps `kind="prepped"`, applies prepared-state primitives (DOR, grounding baseline, review approvals) so the todo is immediately ready for build, and emits the event with `payload.kind="prepped"` so the lifecycle router skips prepare entirely.
- **`telec todo design [<slug>]`** (and the deprecated alias `co-create`) — runs the creative state machine. It does not by itself create a roadmap entry; it inspects creative state for the slug (or auto-selects the next creative work item from the roadmap) and returns the next-action instruction. The creative state machine drives design-spec authoring, art generation, and visual drafting before a downstream creative lifecycle scaffolds the todo.

Bug-kind helpers (`telec bugs report` and `telec bugs create`) wrap the dump path with bug-specific scaffolding and emit `todo_dumped` with `payload.kind="bug"` so the lifecycle router routes the bug to `/next-work` (skipping demo).

All persistence is in `todos.db` (state + artifact + roadmap entry). The Todo aggregate's invariants — unique kebab-case slug, fixed kind, `after` dependencies validated against the roadmap — are enforced before the row is written. `--after` is parsed as a comma-separated list of dependency slugs.

## Canonical fields

### Use cases

```
Given an operator wants to reserve a slug for later content
When they run `telec todo create my-feature --after upstream --kind feature`
Then workflow validates the slug is kebab-case
And validates kind is one of {feature, bug, refactor, migration, prepped}
And inserts a roadmap row at the next position with status=active and a roadmap_deps row per --after entry
And writes a TodoState with kind=feature and lifecycle_phase=draft
And NO artifact is created
And the command prints "Todo created: my-feature"
```

```
Given a human or agent has a substantive idea written up
When they run `telec todo dump my-feature "<content>"`
Then the CLI POSTs to /todos/dump and the server creates state + roadmap entry + an `input` artifact whose body is "# my-feature — Input\n\n<content>\n"
And the CLI emits domain.software-development.planning.todo_dumped with payload.kind="todo"
And the lifecycle router consumes the event and dispatches the prepare orchestrator
```

```
Given a human is still iterating and does not want orchestrator pickup yet
When they run `telec todo dump my-feature "<content>" --draft`
Then the dump request carries kind="draft" so the server stamps state.kind="draft" and lifecycle_phase="draft"
And the `input` artifact is still written with the content
And the planning.todo_dumped event is NOT emitted
And the todo waits silently until the human invokes the next action
```

```
Given a human or agent already has a complete implementation plan
When they run `telec todo dump my-feature "<content>" --prepped`
Then the server writes the content as the `implementation-plan` artifact (body prefixed "# my-feature — Implementation Plan")
And stamps state.kind="prepped"
And applies the prepared-state primitives (DOR, grounding baseline, review approvals) so the canonical lifecycle is immediately `prepared`
And the CLI emits planning.todo_dumped with payload.kind="prepped" so the lifecycle router dispatches build, bypassing prepare
And the CLI prints "Dumped todo: my-feature (prepped, ready for build)"
```

```
Given an operator runs `telec todo dump existing-slug "<content>"` for a slug that already has state
When the server reads existing state and finds it non-null
Then it raises HTTP 409 "Todo 'existing-slug' already exists" and no rows are written
```

```
Given an operator runs `telec todo design my-feature`
When the CLI POSTs to /todos/create with the slug and cwd
Then workflow inspects creative state for the slug
And returns one of: DESIGN_DISCOVERY_REQUIRED, DESIGN_SPEC_PENDING_CONFIRMATION, ART_PENDING_APPROVAL, or the next creative phase instruction
And no roadmap mutation happens for slugs that already exist; design only orchestrates creative phases
```

```
Given a customer-support agent files a bug via `telec bugs report "<description>"`
When the bugs handler scaffolds the bug todo and emits planning.todo_dumped with payload.kind="bug"
Then the lifecycle router consumes the event and dispatches /next-work for the bug lane
And the bug skips the demo phase per the kind=bug lifecycle gate
```

### Implementation pointers (v1)

- `teleclaude/cli/telec/handlers/todo.py:200` — `_handle_todo_create`: parses `<slug> [--after] [--kind]` and calls `create_draft_skeleton`
- `teleclaude/cli/telec/handlers/todo.py:244` — `_handle_todo_dump`: parses `<slug> <content> [--after] [--draft] [--prepped]`, POSTs to `/todos/dump`, emits `planning.todo_dumped` (unless `--draft`)
- `teleclaude/cli/telec/handlers/todo.py:239` — `_handle_todo_design`: delegates to `handle_todo_design`, which POSTs to `/todos/create` to run the creative state machine
- `teleclaude/todo_scaffold.py:72` — `create_draft_skeleton`: validates slug + kind, inserts roadmap row + roadmap_deps, writes default state with `lifecycle_phase="draft"`
- `teleclaude/core/next_machine/_types.py:173` — `default_state` factory used at creation time
- `teleclaude/core/next_machine/create.py:1` — creative state machine entrypoints invoked by `telec todo design`
- `teleclaude/api/todo_routes.py:481` — `POST /todos/dump`: enforces unique-slug guard, performs roadmap + state + artifact writes in a single session, applies prepared-state primitives for `prepped`/`bug`, refreshes artifact digest provenance
- `teleclaude/cli/telec/handlers/bugs.py:30` — `_emit_bug_dumped_event` publishes `planning.todo_dumped` with `payload.kind="bug"`
- `teleclaude/events/cartridges/lifecycle_router.py:20` — lifecycle router subscribes to `domain.software-development.planning.todo_dumped` and dispatches by payload `kind`

### Cross-context references

- `operations` — async, receipt-backed long-running operations (e.g., `/todos/remove`) are surfaced through the operations subsystem; create/dump themselves are synchronous against the daemon API.
- `integration` (event consumer) — the `integration` context hosts the lifecycle router cartridge that consumes `planning.todo_dumped` and dispatches cartridge-appropriate orchestrators (`/next-work`, prepare, etc.).
- `agent_runtime` — the creative state machine driven by `telec todo design` spawns and supervises creative sessions through `agent_runtime`.

## Known caveats

- `--prepped` requires human-in-the-loop per the platform's autonomy policy: an agent does not autonomously bypass prepare. The flag is operator-grade.
- `--draft` is intentionally silent — no event is emitted, so no orchestrator picks it up. The todo waits for a human to invoke the next action.
- The `bugs report` / `bugs create` helpers wrap `dump` with bug-specific scaffolding and route to `/next-work` (skipping demo). Their event payload carries `kind="bug"`; the lifecycle router uses the payload kind, not the todo state, for dispatch decisions.
- `telec todo design` (and the deprecated `co-create` alias) is the creative state machine entrypoint. It is NOT a Todo-creation entrypoint on its own — it orchestrates creative phases (design-spec, art, visuals) against an existing slug or auto-selects from the roadmap. Roadmap scaffolding for design work happens through `create` or `dump` upstream.
- The CLI's `--after` parser splits on commas after trimming; empty entries are dropped. Dependency-existence validation happens at the roadmap layer when the entry is inserted, not in the CLI.
- The `_handle_todo_dump` notification emit is best-effort: if event publication fails, the warning is logged but the dump is not rolled back. Downstream pickup may be delayed until a manual invocation.
- The `prepped` lane writes content prefixed with `# <slug> — Implementation Plan\n\n` and the default `todo` lane writes content prefixed with `# <slug> — Input\n\n`. Callers should not pre-add those headers in the dumped content.
- `default_state()` returns a Pydantic dump of the canonical `TodoState`; kind/lifecycle adjustments are applied on top of that base by the create/dump paths.
