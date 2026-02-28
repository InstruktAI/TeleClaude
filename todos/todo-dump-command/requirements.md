# Requirements: todo-dump-command

## Goal

Add `telec todo dump` — a fire-and-forget brain dump command that scaffolds a todo folder,
writes the user's freeform text into `input.md`, emits a `todo.dumped` notification event
via the notification service, and returns immediately. The notification triggers autonomous
agent processing (prepare, DOR assessment) without human intervention.

## Scope

### In scope

1. **New CLI subcommand** `telec todo dump <description> [--slug <slug>] [--after <deps>] [--project-root PATH]`
   added to the `todo` subcommand group in `CLI_SURFACE` and wired in `_handle_todo`.
2. **Slug auto-generation** from the description when `--slug` is omitted. Same sanitization
   pattern as `telec bugs report` (lowercase, strip non-alnum, truncate at 40 chars).
3. **Scaffold reuse**: call `create_todo_skeleton()` to create the standard todo folder structure.
4. **Brain dump injection**: overwrite the scaffolded `input.md` with the user's freeform
   description text, preserving a `# <slug> — Input` header for consistency.
5. **Notification emission**: after scaffold and write, emit a `todo.dumped` event via the
   notification service producer (`teleclaude_notifications.producer.emit_event`). The event
   payload includes `slug`, `description`, and `project_root`.
6. **Roadmap registration**: the slug is added to `roadmap.yaml` via `add_to_roadmap()`.
   When `--after` is provided, those dependencies are registered. When omitted, the entry
   is added with no dependencies (unlike `create`, which only registers when `--after` is present).
7. **Unit tests** for the new handler: argument parsing, slug generation, error cases.

### Out of scope

- Agent-side processing of the `todo.dumped` event (handled by `prepare-quality-runner` todo).
- Content dump command (`telec content dump`) — separate todo.
- Interactive mode or multi-line input — dump is a single string argument.
- Tags support — deferred until notification service supports metadata filtering.

## Success Criteria

- [ ] `telec todo dump "my idea"` creates `todos/my-idea/` with `input.md` containing the description.
- [ ] Auto-generated slug is clean: lowercase, hyphenated, max 40 chars.
- [ ] `telec todo dump "my idea" --slug custom-name` uses the provided slug.
- [ ] The todo appears in `roadmap.yaml` after dump.
- [ ] A `todo.dumped` notification event is emitted to the Redis stream.
- [ ] `telec todo dump` with no description prints usage and exits non-zero.
- [ ] `telec todo dump "duplicate"` fails gracefully if the slug/folder already exists.
- [ ] `make test` passes with new tests covering the handler.
- [ ] `make lint` passes.

## Constraints

- Must use the existing `create_todo_skeleton()` for folder scaffolding — no duplicate scaffold logic.
- The notification emission requires the notification service package (`teleclaude_notifications`).
  This todo is blocked by `event-platform` in the roadmap.
- CLI handler must be synchronous (matching all existing handlers). Use `asyncio.run()` for the
  async notification emission, following the `bugs report` pattern.
- The `input.md` overwrite must happen after `create_todo_skeleton()` returns, since the skeleton
  creates a template `input.md`.

## Risks

- **Notification service API stability**: the producer API is defined in the event-platform
  implementation plan but not yet built. If the API changes, the emit call must be updated.
  Mitigation: the producer API is simple (`emit_event(event_type, source, ...)`) and stable in design.
- **Redis unavailability**: if Redis is down, the notification emission fails. The scaffold should
  still succeed — emit failure is logged as a warning, not a fatal error. The todo exists and
  can be processed manually or when Redis recovers.
