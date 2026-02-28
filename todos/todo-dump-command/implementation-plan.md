# Implementation Plan: todo-dump-command

## Overview

Add `telec todo dump` as a new subcommand following established CLI patterns. The command
reuses `create_todo_skeleton()` for scaffolding, overwrites `input.md` with the brain dump,
registers the slug in `roadmap.yaml`, and emits a `todo.dumped` notification event via the
notification service producer. The implementation touches three files: the CLI surface
definition, the CLI handler, and tests.

## Phase 1: CLI Surface & Handler

### Task 1.1: Add `dump` to CLI_SURFACE schema

**File(s):** `teleclaude/cli/telec.py`

- [ ] Add `"dump"` entry to the `"todo"` subcommands dict in `CLI_SURFACE`:
  ```python
  "dump": CommandDef(
      desc="Fire-and-forget brain dump with notification trigger",
      args="<description>",
      flags=[
          Flag("--slug", desc="Custom slug (auto-generated if omitted)"),
          Flag("--after", desc="Comma-separated dependency slugs"),
          _PROJECT_ROOT_LONG,
      ],
      notes=["Auto-generates slug from description if --slug is omitted.",
             "Emits todo.dumped notification for autonomous processing."],
  ),
  ```

### Task 1.2: Wire `dump` in `_handle_todo` router

**File(s):** `teleclaude/cli/telec.py`

- [ ] Add `elif subcommand == "dump": _handle_todo_dump(args[1:])` to `_handle_todo()`

### Task 1.3: Implement `_handle_todo_dump` handler

**File(s):** `teleclaude/cli/telec.py`

- [ ] Create `_handle_todo_dump(args: list[str]) -> None` following the `_handle_bugs_report` pattern:
  1. Parse args: positional `description`, optional `--slug`, `--after`, `--project-root`
  2. If no description: print usage, return
  3. If no `--slug`: auto-generate from description (regex sanitize, truncate at 40 chars)
  4. Call `create_todo_skeleton(project_root, slug, after=after_deps)` where `after_deps`
     defaults to `None` when `--after` is omitted
  5. If `--after` is not provided and the slug is not yet in roadmap: call `add_to_roadmap()`
     with no dependencies to ensure the slug is registered
  6. Overwrite `input.md` with brain dump content:
     ```python
     input_path = todo_dir / "input.md"
     input_path.write_text(f"# {slug} — Input\n\n{description}\n")
     ```
  7. Emit `todo.dumped` notification (async, wrapped in `asyncio.run()`):
     ```python
     async def _emit():
         from teleclaude_notifications.producer import NotificationProducer
         producer = NotificationProducer(redis_url=...)
         await producer.emit_event(
             event_type="todo.dumped",
             source="telec-cli",
             level=2,  # WORKFLOW
             domain="todo",
             description=f"Todo dumped: {slug}",
             payload={"slug": slug, "project_root": str(project_root)},
         )
     try:
         asyncio.run(_emit())
     except Exception as exc:
         print(f"Warning: notification emission failed: {exc}")
         print("Todo created successfully. Notification can be retried manually.")
     ```
  8. Print success: `"Dumped todo: todos/{slug}/ — notification sent."`
  9. Handle errors: `FileExistsError` → "Todo already exists", `ValueError` → "Invalid slug"

### Task 1.4: Update telec-cli-surface spec

**File(s):** `docs/project/spec/telec-cli-surface.md`

- [ ] Add `dump` subcommand under `todo` in the machine-readable surface YAML

---

## Phase 2: Validation

### Task 2.1: Tests

**File(s):** `tests/unit/test_telec_todo_cli.py`

- [ ] Test `_handle_todo_dump` argument parsing: description only, with --slug, with --after
- [ ] Test slug auto-generation: lowercase, hyphenated, truncated at 40 chars
- [ ] Test error cases: no description, duplicate slug (FileExistsError)
- [ ] Test `input.md` content after dump: header + description text
- [ ] Test notification emission failure is non-fatal (warning printed, todo still created)
- [ ] Run `make test`

### Task 2.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
