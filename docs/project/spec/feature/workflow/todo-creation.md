---
id: 'project/spec/feature/workflow/todo-creation'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Todo creation in v1 — `telec todo create <slug> <content>` is the substantive primary command (content required), `telec todo dump` is a deprecation alias, and `telec todo design` enters the creative state machine. The server-side `/todos/dump` route emits the `workflow.todo.created` event consumed by the lifecycle router.'
---

# Workflow Todo Creation — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/workflow.md

## What it is

The Todo aggregate inside the `workflow` bounded context is created through two CLI entrypoints that share a single server-side route, plus a creative-machine entrypoint that does not itself create roadmap rows:

- **`telec todo create <slug> <content>`** — the primary, substantive creation command. Both `<slug>` and `<content>` are required positionals; an empty or whitespace-only `<content>` is rejected by the CLI before any network call. The handler builds a `TodoDumpRequest`, POSTs it to `/todos/dump`, and the route writes the todo entry, the default `TodoState`, and an artifact in one transaction. Flags:
  - `--silent` — sets `silent=True` on the request. The route still creates the todo and still emits `workflow.todo.created`, but with `pickup_requested=false` and `creation_mode="silent"`, so the lifecycle router skips dispatch.
  - `--prepped` — sets `kind="prepped"` on the request. The route writes the content as the `implementation-plan` artifact, applies the prepared-state primitives (DOR, grounding baseline, review approvals) so the canonical lifecycle is immediately `prepared`, and the lifecycle router dispatches `/next-work` (build), bypassing prepare.
  - `--after <slugs>` — comma-separated dependency slugs (trimmed; empties dropped); validated against the todo list at insert time.

- **`telec todo dump <slug> <content> [...]`** — DEPRECATED alias for `telec todo create`. Prints a deprecation warning to stderr, translates the legacy `--draft` flag to `--silent`, and forwards everything else verbatim to `_handle_todo_create`. The CLI no longer emits any event from the dump path — every event for a created todo is emitted by the server-side route.

- **`telec todo design [<slug>]`** (and the deprecated alias `co-create`) — runs the creative state machine. It does not create a todo entry on its own; it inspects creative state for the slug (or auto-selects the next creative work item from the todo list) and returns the next-action instruction. Todo scaffolding for design work happens upstream through `create`.

Bug-kind helpers (`telec bugs report` and `telec bugs create`) wrap the same server-side route. Each builds a `TodoDumpRequest(kind="bug", content=<bug-body>)` and POSTs to `/todos/dump`. The route writes a `bug` artifact (not `input`), applies prepared-state primitives, and emits `workflow.todo.created` with canonical `kind="bug"`. There is no CLI-side event emit in the bugs handler — the prior `_emit_bug_dumped_event` helper has been removed.

All persistence is in `todos.db` (state + artifact + todo entry). The Todo aggregate's invariants — unique kebab-case slug, fixed kind, `after` dependencies validated against the todo list — are enforced before the row is written. The route is the single emission point for `workflow.todo.created`; the v1 CLI surface no longer publishes lifecycle events directly.

## Canonical fields

### `workflow.todo.created` payload (v1 partial shape)

The route emits the event with this payload:

- `slug` — the created slug.
- `kind` — canonical kind, mapped via `map_v1_kind_to_canonical`: `None`/`"prepped"`/`"draft"` → `"feature"`; `"bug"` → `"bug"`; canonical kinds (`"feature"`, `"refactor"`, `"migration"`) pass through.
- `creation_mode` — `"silent"` when the request had `silent=True`, otherwise `"pickup"`.
- `pickup_requested` — boolean, equal to `not request.silent`.
- `lifecycle_phase` — the post-write `lifecycle_phase` value (`"prepared"` for `prepped` and `bug`, `"draft"` otherwise).
- `created_at` — UTC ISO-8601 timestamp.
- `project_path` — effective cwd used to resolve the project's `todos.db`.

Fields `todo_id`, `project_id`, and `created_by_principal` are intentionally absent in the v1 partial shape; v2 consumers fill them via serde defaults.

### Use cases

```
Given a human or agent has a substantive idea written up
When they run `telec todo create my-feature "<content>"`
Then the CLI validates that <content> is non-empty
And POSTs a TodoDumpRequest to /todos/dump with kind=None, silent=False
And the route creates the todo entry, default TodoState, and an `input` artifact whose body is "# my-feature — Input\n\n<content>\n" in one transaction
And the route emits workflow.todo.created with kind="feature" and pickup_requested=true
And the lifecycle router consumes the event and dispatches /next-prepare
And the CLI prints "Created todo: my-feature"
```

```
Given a human is still iterating and does not want orchestrator pickup yet
When they run `telec todo create my-feature "<content>" --silent`
Then the request carries silent=True
And the route still writes state + roadmap + `input` artifact identically to the default path
And the route emits workflow.todo.created with pickup_requested=false and creation_mode="silent"
And the lifecycle router observes pickup_requested=false and logs "skipped: pickup_requested=False" without dispatching
And the todo waits silently until a human invokes the next action
```

```
Given a human or agent already has a complete implementation plan
When they run `telec todo create my-feature "<content>" --prepped`
Then the request carries kind="prepped"
And the route writes the content as the `implementation-plan` artifact (body prefixed "# my-feature — Implementation Plan")
And the route applies the prepared-state primitives so lifecycle_phase becomes "prepared"
And the route emits workflow.todo.created with canonical kind="feature" and pickup_requested=true
And the lifecycle router dispatches /next-work (build), bypassing prepare
And the CLI prints "Created todo: my-feature (prepped, ready for build)"
```

```
Given an operator runs `telec todo dump my-feature "<content>"`
When the deprecation alias prints the warning to stderr and forwards to _handle_todo_create
Then the request carries kind=None, silent=False (no event is emitted by the CLI)
And the route behavior matches `telec todo create my-feature "<content>"` exactly
And the legacy `--draft` flag, if present, is translated to `--silent` before forwarding
```

```
Given an operator runs `telec todo create existing-slug "<content>"`
When the route reads existing state and finds it non-null
Then it raises HTTP 409 "Todo 'existing-slug' already exists" and no rows are written
And no event is emitted
```

```
Given an operator runs `telec todo create my-feature ""` (or with only whitespace)
When the CLI parses the positional arguments
Then it prints "Error: <content> is required and must not be empty" and exits non-zero
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

- `teleclaude/cli/telec/handlers/todo.py:199` — `_handle_todo_create`: parses `<slug> <content> [--after] [--silent] [--prepped]`, rejects empty content, builds `TodoDumpRequest`, POSTs to `/todos/dump`. No CLI-side event emission.
- `teleclaude/cli/telec/handlers/todo.py:267` — `_handle_todo_design`: delegates to `handle_todo_design`, which POSTs to `/todos/create` to run the creative state machine.
- `teleclaude/cli/telec/handlers/todo.py:272` — `_handle_todo_dump`: deprecation alias. Writes the warning to stderr, rewrites `--draft` to `--silent`, and forwards to `_handle_todo_create`.
- `teleclaude/cli/telec/handlers/bugs.py:58` — `_handle_bugs_create`: builds `TodoDumpRequest(kind="bug")` and POSTs to `/todos/dump`. No CLI-side event emission.
- `teleclaude/cli/telec/handlers/bugs.py:125` — `_handle_bugs_report`: same shape as `_handle_bugs_create`, with optional `--body` appended to the bug content.
- `teleclaude/api/todo_routes.py:534` — `POST /todos/dump`: enforces the unique-slug guard and the non-empty-content guard, performs roadmap + state + artifact writes in a single session, applies prepared-state primitives for `prepped` / `bug`, refreshes artifact digest provenance, and emits `workflow.todo.created` (skipping the emit only when `kind=="draft"`).
- `teleclaude/api/todo_routes.py:609` — event emission site for `workflow.todo.created`.
- `teleclaude/api/kind_mapper.py` — `map_v1_kind_to_canonical`: maps v1 `kind` (incl. `None`, `"prepped"`, `"draft"`) onto the canonical event kind set (`feature`, `bug`, `refactor`, `migration`).
- `teleclaude/todo_scaffold.py:72` — `create_draft_skeleton`: skeleton helper used by the route for the todo-list + default-state path; the route composes it with the artifact write inside one session.
- `teleclaude/core/next_machine/_types.py` — `default_state` factory used at creation time.
- `teleclaude/core/next_machine/create.py:1` — creative state machine entrypoints invoked by `telec todo design`.
- `teleclaude/events/cartridges/lifecycle_router.py:24` — `_TRIGGER_EVENTS` includes `workflow.todo.created`.
- `teleclaude/events/cartridges/lifecycle_router.py:57` — `workflow.todo.created` handler: checks `pickup_requested`, then dispatches by canonical `kind` (`bug` → `/next-work` claude/slow; `prepped`/`built` → `/next-work`; `feature`/`refactor`/`migration` → `/next-prepare`).

### Cross-context references

- `operations` — async, receipt-backed long-running operations (e.g., `/todos/remove`) are surfaced through the operations subsystem; create itself is synchronous against the daemon API.
- `integration` (event consumer) — the `integration` context hosts the lifecycle router cartridge that consumes `workflow.todo.created` and dispatches cartridge-appropriate orchestrators (`/next-prepare`, `/next-work`).
- `agent_runtime` — the creative state machine driven by `telec todo design` spawns and supervises creative sessions through `agent_runtime`.

## Known caveats

- `<content>` is now a required positional on `telec todo create`. Empty or whitespace-only content is rejected by the CLI before any network call; the server route also rejects it with HTTP 400 as a second line of defense. The previous "reserve a slug, fill content later" workflow no longer exists at the CLI surface.
- `telec todo dump` still works but is a deprecation alias. Every invocation prints a warning to stderr and forwards to `telec todo create`. The legacy `--draft` flag is rewritten to `--silent` for forward compatibility; no other behavioral difference remains.
- `--silent` does NOT suppress the event. The route always emits `workflow.todo.created` (except when `kind=="draft"`, an internal-only branch with no CLI surface in v1 anymore). `--silent` flips `pickup_requested` to `false`, and the lifecycle router uses that field to decide whether to dispatch.
- `--prepped` requires human-in-the-loop per the platform's autonomy policy: an agent does not autonomously bypass prepare. The flag is operator-grade.
- The `bugs report` / `bugs create` helpers wrap the same `/todos/dump` route with `kind="bug"`. The prior CLI-side `_emit_bug_dumped_event` helper has been deleted; the route is now the single emission point for bug creation as well.
- The lifecycle router routes purely on the event payload's `kind` and `pickup_requested`; it does not read todo state during dispatch. Missing/unknown kinds degrade to the default todo lane (`/next-prepare`).
- `telec todo design` (and the deprecated `co-create` alias) is the creative state machine entrypoint. It is NOT a Todo-creation entrypoint on its own — it orchestrates creative phases (design-spec, art, visuals) against an existing slug or auto-selects from the todo list.
- The CLI's `--after` parser splits on commas after trimming; empty entries are dropped. Dependency-existence validation happens when the entry is inserted, not in the CLI.
- The `prepped` lane writes content prefixed with `# <slug> — Implementation Plan\n\n` and the default lane writes content prefixed with `# <slug> — Input\n\n`. Callers should not pre-add those headers in the supplied content.
- The v1 `workflow.todo.created` payload is intentionally partial: `todo_id`, `project_id`, and `created_by_principal` are not populated by v1; v2 consumers fill them via serde defaults.
- `default_state()` returns a Pydantic dump of the canonical `TodoState`; kind/lifecycle adjustments are applied on top of that base by the route.
