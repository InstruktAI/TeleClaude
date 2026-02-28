# Requirements: content-dump-command

## Goal

Add `telec content dump` — a fire-and-forget CLI command that creates a publications
inbox entry and fires a notification event for downstream processing. The human dumps
raw content; the system takes it from there.

## Scope

### In scope

1. **New `content` CLI subgroup** — add `telec content` with `dump` as its first subcommand.
2. **Inbox entry scaffolding** — create `publications/inbox/YYYYMMDD-<slug>/` with:
   - `content.md` — the raw brain dump text.
   - `meta.yaml` — author, tags, and timestamp metadata.
3. **Slug generation** — auto-generate a dated slug (`YYYYMMDD-<slug>`) from the provided
   text when `--slug` is omitted. Use the first few meaningful words of the description.
4. **Notification emission** — emit a `content.dumped` event via the notification service
   producer utility (`xadd` to Redis Streams). The event payload includes the inbox path,
   author, and tags.
5. **Immediate return** — the command writes files and fires the event synchronously, then
   exits. No downstream processing is awaited.
6. **CLI surface registration** — the `content` subgroup and `dump` subcommand appear in
   help output, completion, and the CLI surface spec.
7. **Author resolution** — default author is the current terminal identity (`telec auth whoami`)
   or `"unknown"` if not authenticated. Overridable via `--author`.

### Out of scope

- `telec content create` (manual iteration mode) — future subcommand, not this todo.
- Writer/publisher agent logic — consumes the notification; separate concern.
- Content processing pipeline — downstream of the dump event.
- TUI integration for content management.
- Any changes to the publications README or inbox schema.

## Success Criteria

- [ ] `telec content dump "My content here"` creates a dated folder in `publications/inbox/`.
- [ ] The folder contains `content.md` with the provided text and `meta.yaml` with author/tags.
- [ ] A `content.dumped` notification event is emitted to Redis Streams.
- [ ] `telec content dump --help` shows correct usage.
- [ ] Slug auto-generation produces readable, valid folder names.
- [ ] `--slug`, `--tags`, and `--author` flags work as documented.
- [ ] `make test` passes with tests covering scaffolding and CLI parsing.
- [ ] `make lint` passes.

## Constraints

- Must follow existing CLI patterns (`telec.py` `CLI_SURFACE` dict, `TelecCommand` enum,
  `_handle_*` dispatch).
- Notification emission depends on the notification-service package being built and the
  `content.dumped` event schema being registered. If notification-service is not yet
  available at build time, the notification call must be guarded (emit if available,
  warn and skip if not).
- Inbox folder naming must match the established convention: `YYYYMMDD-<slug>`.
- The command must be synchronous (no `asyncio.run` in the CLI path) — file writes and
  the Redis `XADD` are fast enough to be blocking.

## Risks

- **Notification-service not yet built:** the `content.dumped` event schema and producer
  utility may not exist at implementation time. Mitigation: guard the notification call
  behind an import check; the command works without notifications (creates files, warns
  that notification was skipped).
- **Slug collision:** two dumps on the same day with similar text could collide.
  Mitigation: append a short counter or hash suffix when the folder already exists.
