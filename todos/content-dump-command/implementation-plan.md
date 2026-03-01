# Implementation Plan: content-dump-command

## Overview

Add the `telec content dump` command following the established CLI patterns. The work
is a CLI subcommand with file scaffolding and notification emission — structurally
identical to how `telec todo create` scaffolds todo folders, with the addition of a
notification event.

## Phase 1: CLI Surface

### Task 1.1: Add `content` to TelecCommand enum and CLI_SURFACE

**File(s):** `teleclaude/cli/telec.py`

- [x] Add `CONTENT = "content"` to the `TelecCommand` enum
- [x] Add `"content"` entry to `CLI_SURFACE` dict with `dump` subcommand:
  ```python
  "content": CommandDef(
      desc="Manage content pipeline",
      subcommands={
          "dump": CommandDef(
              desc="Fire-and-forget content dump to publications inbox",
              args="<description-or-text>",
              flags=[
                  Flag("--slug", desc="Custom slug (default: auto-generated from text)"),
                  Flag("--tags", desc="Comma-separated tags"),
                  Flag("--author", desc="Author identity (default: terminal auth)"),
                  _PROJECT_ROOT_LONG,
              ],
          ),
      },
  )
  ```

### Task 1.2: Add `_handle_content` dispatch

**File(s):** `teleclaude/cli/telec.py`

- [x] Add `_handle_content(args)` function routing to `_handle_content_dump`
- [x] Wire `TelecCommand.CONTENT` in the main dispatch block (around line 1209)

### Task 1.3: Implement `_handle_content_dump`

**File(s):** `teleclaude/cli/telec.py`

- [x] Parse CLI args: positional text, `--slug`, `--tags`, `--author`, `--project-root`
- [x] Call `create_content_inbox_entry()` from the scaffolding module
- [x] Attempt notification emission (guarded import)
- [x] Print confirmation with the created path

## Phase 2: Content Scaffolding

### Task 2.1: Create content scaffolding module

**File(s):** `teleclaude/content_scaffold.py`

- [x] `create_content_inbox_entry(project_root, text, *, slug=None, tags=None, author=None) -> Path`
- [x] Generate dated slug: `YYYYMMDD-<slug>` where slug is derived from text or provided
- [x] Slug derivation: lowercase, strip non-alphanum, take first 4-5 words, join with hyphens
- [x] Handle collision: if folder exists, append `-2`, `-3`, etc.
- [x] Write `content.md` with the raw text
- [x] Write `meta.yaml` with author, tags, and `created_at` timestamp
- [x] Return the created directory path

### Task 2.2: Author resolution

**File(s):** `teleclaude/content_scaffold.py`

- [x] Default author: read from `telec auth whoami` equivalent (import `read_current_session_email`)
- [x] If no auth identity, use session env or fall back to `"unknown"`
- [x] `--author` flag overrides all defaults

## Phase 3: Notification

### Task 3.1: Emit `content.dumped` event

**File(s):** `teleclaude/content_scaffold.py` or `teleclaude/cli/telec.py`

- [x] Guard notification import behind try/except (event-platform may not exist yet)
- [x] If available, call the producer utility to XADD `content.dumped` with payload:
  ```yaml
  event_type: content.dumped
  entity_ref: publications/inbox/YYYYMMDD-slug
  payload:
    inbox_path: publications/inbox/YYYYMMDD-slug
    author: <author>
    tags: [<tags>]
  ```
- [x] If not available, print warning: "Notification service not available, skipping event emission"
- [x] This task is deferred if event-platform is not built yet — the guard ensures
      the command works without it

---

## Phase 4: Validation

### Task 4.1: Tests

- [x] Test `create_content_inbox_entry` creates correct folder structure
- [x] Test slug auto-generation from text
- [x] Test slug collision handling
- [x] Test `meta.yaml` contains expected fields
- [x] Test CLI arg parsing for `telec content dump`
- [x] Run `make test`

### Task 4.2: Quality Checks

- [x] Run `make lint`
- [x] Verify no unchecked implementation tasks remain

---

## Phase 5: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)
