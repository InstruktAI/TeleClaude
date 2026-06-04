---
id: 'project/spec/feature/workflow/todo-creation'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Todo creation in v1 — `telec todo create <slug> <content> --kind <kind>` is the single creation command (kind and content required), and `telec todo design` enters the creative state machine. The server-side `/todos/dump` route emits the `workflow.todo.created` event consumed by the lifecycle router.'
---

# Workflow Todo Creation — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

The Todo aggregate inside the `workflow` bounded context is created through one CLI entrypoint that calls a single server-side route, plus a creative-machine entrypoint that does not itself create roadmap rows:

- **`telec todo create <slug> <content> --kind <kind>`** — the single creation command. Both `<slug>` and `<content>` are required positionals; an empty or whitespace-only `<content>` is rejected by the CLI before any network call. `--kind` is a required flag — no default, no fallback, missing kind exits with a usage error. The handler builds a `TodoDumpRequest`, POSTs it to `/todos/dump`, and the route writes the todo entry, the default `TodoState`, and an artifact in one transaction. Flags:
  - `--kind <kind>` — **required**. Canonical kind value from `teleclaude.types.todo_kind`. Valid values: `feature`, `refactor`, `migration`, `todo` (→ prepare lane), `bug` (→ bug-fix lane), `prepped` (content is a complete plan; skip prepare), `draft` (park idea; no lifecycle). No default — callers must be explicit.
  - `--silent` — sets `silent=True` on the request. The route still creates the todo and still emits `workflow.todo.created`, but with `pickup_requested=false` and `creation_mode="silent"`, so the lifecycle router skips dispatch.
  - `--after <slugs>` — comma-separated dependency slugs (trimmed; empties dropped); validated against the todo list at insert time.

- **`telec todo design [<slug>]`** (and the deprecated alias `co-create`) — runs the creative state machine. It does not create a todo entry on its own; it inspects creative state for the slug (or auto-selects the next creative work item from the todo list) and returns the next-action instruction. Todo scaffolding for design work happens upstream through `create`.

Bug-kind helpers (`telec bugs report` and `telec bugs create`) wrap the same server-side route. Each builds a `TodoDumpRequest(kind="bug", content=<bug-body>)` and POSTs to `/todos/dump`. The route writes a `bug` artifact (not `input`), applies prepared-state primitives, and emits `workflow.todo.created` with canonical `kind="bug"`. There is no CLI-side event emit in the bugs handler — the prior `_emit_bug_dumped_event` helper has been removed.

All persistence is in `todos.db` (state + artifact + todo entry). The Todo aggregate's invariants — unique kebab-case slug, fixed kind, `after` dependencies validated against the todo list — are enforced before the row is written. The route is the single emission point for `workflow.todo.created`; the v1 CLI surface no longer publishes lifecycle events directly.

## Canonical fields

### `workflow.todo.created` payload (v1 partial shape)

The route emits the event with this payload:

- `slug` — the created slug.
- `kind` — canonical kind, mapped via `map_v1_kind_to_canonical`: `None`/`""` → `"feature"`; `"draft"` → `"feature"`; `"prepped"` → `"prepped"` (routes `/next-work` bypass lane); `"bug"` → `"bug"`; canonical kinds (`"feature"`, `"refactor"`, `"migration"`, `"todo"`) pass through.
- `creation_mode` — `"silent"` when the request had `silent=True`, otherwise `"pickup"`.
- `pickup_requested` — boolean, equal to `not request.silent`.
- `lifecycle_phase` — the post-write `lifecycle_phase` value (`"prepared"` for `prepped` and `bug`, `"draft"` otherwise).
- `created_at` — UTC ISO-8601 timestamp.
- `project_path` — effective cwd used to resolve the project's `todos.db`.

Fields `todo_id`, `project_id`, and `created_by_principal` are intentionally absent in the v1 partial shape; v2 consumers fill them via serde defaults.

### Use cases

```
Given a human or agent has a substantive idea written up
When they run `telec todo create my-feature "<content>" --kind feature`
Then the CLI validates that <content> is non-empty and --kind is present
And POSTs a TodoDumpRequest to /todos/dump with kind="feature", silent=False
And the route creates the todo entry, default TodoState, and an `input` artifact whose body is "# my-feature — Input\n\n<content>\n" in one transaction
And the route emits workflow.todo.created with kind="feature" and pickup_requested=true
And the lifecycle router consumes the event and dispatches /next-prepare
And the CLI prints "Created todo: my-feature"
```

```
Given a human is still iterating and does not want orchestrator pickup yet
When they run `telec todo create my-feature "<content>" --kind feature --silent`
Then the request carries kind="feature", silent=True
And the route still writes state + roadmap + `input` artifact identically to the default path
And the route emits workflow.todo.created with pickup_requested=false and creation_mode="silent"
And the lifecycle router observes pickup_requested=false and logs "skipped: pickup_requested=False" without dispatching
And the todo waits silently until a human invokes the next action
```

```
Given a human or agent already has a complete implementation plan
When they run `telec todo create my-feature "<content>" --kind prepped`
Then the request carries kind="prepped"
And the route writes the content as the `implementation-plan` artifact (body prefixed "# my-feature — Implementation Plan")
And the route applies the prepared-state primitives so lifecycle_phase becomes "prepared"
And the route emits workflow.todo.created with canonical kind="prepped" and pickup_requested=true
And the lifecycle router dispatches /next-work (build), bypassing prepare
And the CLI prints "Created todo: my-feature (kind=prepped)"
```

```
Given an operator runs `telec todo create existing-slug "<content>" --kind feature`
When the route reads existing state and finds it non-null
Then it raises HTTP 409 "Todo 'existing-slug' already exists" and no rows are written
And no event is emitted
```

```
Given an operator runs `telec todo create my-feature "" --kind feature` (or with only whitespace)
When the CLI parses the positional arguments
Then it prints "Error: <content> is required and must not be empty" and exits non-zero
And no network call is made
```

```
Given an operator creates a todo with content but omits `--kind`
When the CLI parses the flags
Then it prints "Error: --kind is required" and exits non-zero
And no network call is made
```

```
Given an operator runs `telec todo design my-feature`
When the CLI delegates to `handle_todo_design`, which POSTs to /todos/create with the slug and cwd
Then workflow inspects creative state for the slug
And returns one of: DESIGN_DISCOVERY_REQUIRED, DESIGN_SPEC_PENDING_CONFIRMATION, ART_PENDING_APPROVAL, or the next creative phase instruction
And no roadmap mutation happens for slugs that already exist; design only orchestrates creative phases
```

```
Given a customer-support agent files a bug via `telec bugs report "<description>"`
When the bugs handler builds a TodoDumpRequest(kind="bug") and POSTs it to /todos/dump
Then the route writes state + roadmap + `bug` artifact and applies prepared-state primitives
And the route emits workflow.todo.created with canonical kind="bug" and pickup_requested=true
And the lifecycle router consumes the event and dispatches /next-work for the bug lane (claude/slow)
And the bug skips the demo phase per the kind=bug lifecycle gate
```

### Implementation pointers (v1)

- `teleclaude/cli/telec/handlers/todo.py` — `_handle_todo_create`: parses `<slug> <content> --kind <kind> [--after] [--silent]`, rejects empty content, rejects missing `--kind` with a usage error (no default), validates kind against `ALL_DUMP_KINDS`, builds `TodoDumpRequest`, POSTs to `/todos/dump`. No CLI-side event emission.
- `teleclaude/cli/telec/handlers/todo.py` — `_handle_todo_design`: delegates to `handle_todo_design`, which POSTs to `/todos/create` to run the creative state machine.
- `teleclaude/cli/telec/handlers/bugs.py` — `_handle_bugs_create`: builds `TodoDumpRequest(kind=TODO_KIND_BUG)` and POSTs to `/todos/dump`. No CLI-side event emission.
- `teleclaude/cli/telec/handlers/bugs.py` — `_handle_bugs_report`: same shape as `_handle_bugs_create`, with optional `--body` appended to the bug content.
- `teleclaude/api/todo_routes.py` — `POST /todos/dump`: enforces the unique-slug guard and the non-empty-content guard, performs roadmap + state + artifact writes in a single session, applies prepared-state primitives for `prepped` / `bug`, refreshes artifact digest provenance, and emits `workflow.todo.created` (skipping the emit only when `kind=="draft"`).
- `teleclaude/api/todo_routes.py` — event emission site for `workflow.todo.created`.
- `teleclaude/api/kind_mapper.py` — `map_v1_kind_to_canonical`: maps v1 `kind` onto the canonical event kind set; `None`/`""` → `"feature"`; `"draft"` → `"feature"`; `"prepped"` → `"prepped"` (routes `/next-work` bypass lane); `"bug"` → `"bug"`; `"feature"`, `"refactor"`, `"migration"`, `"todo"` pass through.
- `teleclaude/types/todo_kind.py` — canonical source of truth for all kind constants (`TODO_KIND_*`), `ALL_DUMP_KINDS`, `PREPARE_LANE_KINDS`, and the `TodoDumpKind` Literal type.
- `teleclaude/todo_scaffold.py` — `create_draft_skeleton`: skeleton helper used by the route for the todo-list + default-state path; the route composes it with the artifact write inside one session.
- `teleclaude/core/next_machine/_types.py` — `default_state` factory used at creation time.
- `teleclaude/core/next_machine/create.py:1` — creative state machine entrypoints invoked by `telec todo design`.
- `teleclaude/events/cartridges/lifecycle_router.py` — `_TRIGGER_EVENTS` includes `workflow.todo.created`.
- `teleclaude/events/cartridges/lifecycle_router.py` — `workflow.todo.created` handler: checks `pickup_requested`, then dispatches by canonical `kind` (`bug` → `/next-work` claude/slow; `prepped`/`built` → `/next-work`; `feature`/`refactor`/`migration`/`todo` → `/next-prepare`).

### Cross-context references

- `operations` — async, receipt-backed long-running operations (e.g., `/todos/remove`) are surfaced through the operations subsystem; create itself is synchronous against the daemon API.
- `integration` (event consumer) — the `integration` context hosts the lifecycle router cartridge that consumes `workflow.todo.created` and dispatches cartridge-appropriate orchestrators (`/next-prepare`, `/next-work`).
- `agent_runtime` — the creative state machine driven by `telec todo design` spawns and supervises creative sessions through `agent_runtime`.

## Known caveats

- `<content>` is a required positional on `telec todo create`. Empty or whitespace-only content is rejected by the CLI before any network call; the server route also rejects it with HTTP 400 as a second line of defense.
- `--kind` is **required** on `telec todo create`. Omitting it exits with a usage error and no API call is made. There is no default — callers must be explicit. The full set of valid kinds is defined in `teleclaude/types/todo_kind.py` as `ALL_DUMP_KINDS`. Use `--kind prepped` to skip the prepare phase (HUMAN-IN-THE-LOOP required).
- `--silent` does NOT suppress the event. The route always emits `workflow.todo.created` (except when `kind=="draft"`, an internal-only lane with no CLI surface). `--silent` flips `pickup_requested` to `false`, and the lifecycle router uses that field to decide whether to dispatch.
- `--kind prepped` requires human-in-the-loop per the platform's autonomy policy: an agent does not autonomously bypass prepare. Operator-grade.
- The `bugs report` / `bugs create` helpers wrap the same `/todos/dump` route with `kind=TODO_KIND_BUG`. The prior CLI-side `_emit_bug_dumped_event` helper has been deleted; the route is now the single emission point for bug creation as well.
- The lifecycle router routes purely on the event payload's `kind` and `pickup_requested`; it does not read todo state during dispatch. Missing/unknown kinds degrade to the default todo lane (`/next-prepare`).
- `telec todo design` (and the deprecated `co-create` alias) is the creative state machine entrypoint. It is NOT a Todo-creation entrypoint on its own — it orchestrates creative phases (design-spec, art, visuals) against an existing slug or auto-selects from the todo list.
- The CLI's `--after` parser splits on commas after trimming; empty entries are dropped. Dependency-existence validation happens when the entry is inserted, not in the CLI.
- The `prepped` lane writes content prefixed with `# <slug> — Implementation Plan\n\n` and the default lane writes content prefixed with `# <slug> — Input\n\n`. Callers should not pre-add those headers in the supplied content.
- The v1 `workflow.todo.created` payload is intentionally partial: `todo_id`, `project_id`, and `created_by_principal` are not populated by v1; v2 consumers fill them via serde defaults.
- `default_state()` returns a Pydantic dump of the canonical `TodoState`; kind/lifecycle adjustments are applied on top of that base by the route.
