---
description: 'v2 logging/observability model: crates/observability wraps tracing, output matches the instrukt_ai_logging Python standard.'
visibility: 'public'
---

# Observability Model — Design

## Required reads

- docs/project/design/architecture-v2/transport-rules.md
- docs/project/design/architecture-v2/file-layout.md

## Purpose

Every v2 Rust binary writes logs to the same destinations as v1 Python, in
the same format, so the existing `instrukt-ai-logs` query tool reads both
transparently. Achieved via a thin Rust crate that wraps `tracing` with a
custom subscriber emitting the `instrukt_ai_logging` JSON format.

## Inputs/Outputs

**Inputs:**

- the existing `instrukt_ai_logging` Python lib (shared InstruktAI logging
  standard, reusable across projects)

<!-- planned-change:adopt-xdg-user-space-logger -->

- the canonical log path: `/var/log/instrukt-ai/teleclaude/<source>.log`

<!-- change:adopt-xdg-user-space-logger -->

- the canonical log path: `~/.local/state/instrukt-ai/teleclaude/<source>.log`

<!-- /planned-change:adopt-xdg-user-space-logger -->

- the existing `instrukt-ai-logs` CLI tool that merges across these files
- v2's services-as-crates model

**Outputs:**

- the `crates/observability/` crate's role and surface
- per-binary initialization pattern
- per-service logging pattern
- the on-disk format that both v1 and v2 write

## Invariants

- **One logging facility for v2.** All Rust binaries use `crates/observability/`
  for log initialization. Every service crate uses `tracing::*` macros for
  structured logging.

<!-- planned-change:adopt-xdg-user-space-logger -->

- **Same destination as v1.** Output goes to
  `/var/log/instrukt-ai/teleclaude/<source>.log`. The directory and the
  source-name convention match v1.

<!-- change:adopt-xdg-user-space-logger -->

- **Same destination as v1.** Output goes to
  `~/.local/state/instrukt-ai/teleclaude/<source>.log`. The directory and the
  source-name convention match v1.

<!-- /planned-change:adopt-xdg-user-space-logger -->

- **Same format as v1.** `logfmt` lines (key=value pairs) matching the
  `instrukt_ai_logging` Python lib's output. Field names match.
  `instrukt-ai-logs` reads Rust and Python output indistinguishably.
- **Per-binary source name.** Each binary picks a source name at startup.
  `telec`, `telec-daemon`, `telec-tui`, `telec-api`, and worker binaries each
  get their own log file. `instrukt-ai-logs teleclaude` merges across files.
- **No shared-file coordination.** Each binary writes to its own file. The
  query tool merges; the binaries don't coordinate writes.

## Primary flows

### The observability crate

`crates/observability/` is an infrastructure crate (cross-cutting, used by
every binary). It exposes:

<!-- planned-change:adopt-xdg-user-space-logger -->

- `init(source: &str)` — binary `main` calls this first. Configures
  `tracing-subscriber` to write `logfmt` lines (`ts=… level=… logger=…
msg=… <structured fields>`) matching the `instrukt_ai_logging` Python
  schema to `/var/log/instrukt-ai/teleclaude/<source>.log`. Honors
  `TELECLAUDE_LOG_LEVEL` env var.

<!-- change:adopt-xdg-user-space-logger -->

- `init(source: &str)` — binary `main` calls this first. Configures
  `tracing-subscriber` to write `logfmt` lines (`ts=… level=… logger=…
msg=… <structured fields>`) matching the `instrukt_ai_logging` Python
  schema to `~/.local/state/instrukt-ai/teleclaude/<source>.log`. Honors
  `TELECLAUDE_LOG_LEVEL` env var.

<!-- /planned-change:adopt-xdg-user-space-logger -->

- Optional: re-export `tracing` macros for convenience, or have callers
  depend on `tracing` directly.

Internal modules (`_writer.rs`, etc.) implement the JSON format and file
writing. Other crates never reach inside.

### Binary initialization

Every binary's `main` calls `observability::init(...)` before anything else
runs:

```rust
fn main() {
    observability::init("telec-daemon");
    // ... rest of startup
}
```

The source name selects the log file. Conventionally one per binary:

<!-- planned-change:adopt-xdg-user-space-logger -->

| Binary          | Source name     | Log file                                            |
| --------------- | --------------- | --------------------------------------------------- |
| `telec`         | `telec`         | `/var/log/instrukt-ai/teleclaude/telec.log`         |
| `telec-tui`     | `telec-tui`     | `/var/log/instrukt-ai/teleclaude/telec-tui.log`     |
| `telec-daemon`  | `telec-daemon`  | `/var/log/instrukt-ai/teleclaude/telec-daemon.log`  |
| `telec-api`     | `telec-api`     | `/var/log/instrukt-ai/teleclaude/telec-api.log`     |
| worker binaries | `worker-<name>` | `/var/log/instrukt-ai/teleclaude/worker-<name>.log` |

<!-- change:adopt-xdg-user-space-logger -->

| Binary          | Source name     | Log file                                                  |
| --------------- | --------------- | --------------------------------------------------------- |
| `telec`         | `telec`         | `~/.local/state/instrukt-ai/teleclaude/telec.log`         |
| `telec-tui`     | `telec-tui`     | `~/.local/state/instrukt-ai/teleclaude/telec-tui.log`     |
| `telec-daemon`  | `telec-daemon`  | `~/.local/state/instrukt-ai/teleclaude/telec-daemon.log`  |
| `telec-api`     | `telec-api`     | `~/.local/state/instrukt-ai/teleclaude/telec-api.log`     |
| worker binaries | `worker-<name>` | `~/.local/state/instrukt-ai/teleclaude/worker-<name>.log` |

<!-- /planned-change:adopt-xdg-user-space-logger -->

v1 Python daemon's source is `teleclaude` (its log file is
`teleclaude.log`). v2 binaries get distinct source names so v1 and v2 logs
sit side-by-side during transition. `instrukt-ai-logs teleclaude` merges
all of them.

### Service-level logging

Service crates use standard `tracing` macros. No custom logger setup,
no service-specific logger configuration:

```rust
use tracing::{info, error, warn, debug};

pub async fn create_todo(ctx: &Context, input: TodoInput) -> Result<Todo> {
    info!(slug = %input.slug, "creating todo");
    let todo = _storage::insert(ctx, input).await
        .map_err(|err| {
            error!(?err, slug = %input.slug, "failed to create todo");
            err
        })?;
    info!(slug = %todo.slug, id = %todo.id, "todo created");
    Ok(todo)
}
```

The `observability` crate's subscriber captures these macros and emits the
JSON format to the configured log file. Structured fields (`slug`, `id`,
`err`) become JSON fields, not concatenated into the message string.

### On-disk format

`logfmt` — one log event per line, key=value pairs space-separated.
Schema matches the `instrukt_ai_logging` Python lib's output. Standard
fields:

- `ts` — ISO 8601 timestamp with timezone
- `level` — `DEBUG | INFO | WARN | ERROR`
- `logger` — module path or service name
- `msg` — the human-readable message (quoted if it contains spaces)
- additional `key=value` structured fields from the call site

Exact field names and value formatting follow the Python lib's schema.
v2's `crates/observability/` reads `instrukt_ai_logging`'s Python source
to match formatting byte-for-byte where it matters (timestamp format,
field ordering, quoting rules).

### Query

The existing `instrukt-ai-logs` CLI works unchanged:

```
instrukt-ai-logs teleclaude --since 5m              # merges all .log files
instrukt-ai-logs teleclaude --since 5m --grep ERROR # filters by content
```

Rust and Python lines interleave in chronological order. The operator
experience is identical to v1.

### Optional future: extract the Rust crate to a sibling package

If `instrukt_ai_logging` is meant to be reusable across InstruktAI projects
(the Python lib already is), the Rust counterpart could eventually be
extracted to a sibling published package — `instrukt-ai-logging-rs`. Then
any Rust project at InstruktAI imports the same standard.

For v2 TeleClaude, this is not needed today. `crates/observability/`
inside the workspace is sufficient. Extraction happens later if/when a
second Rust project at InstruktAI wants the same standard.

## Failure modes

- **Each service crate setting up its own subscriber.** Causes log
  duplication or fights between subscribers. Initialization happens once
  per binary, in `main`, before any service code runs.
- **Concatenated messages instead of structured fields.** `error!(format!(
"failed for slug {}", slug))` instead of `error!(slug = %slug, "failed")`.
  Defeats structured log queries.
- **Writing to a shared file across binaries.** Append-mode concurrent
  writes to one file work for small messages but introduce race risk.
  Each binary writes to its own file; the query tool merges.

<!-- planned-change:adopt-xdg-user-space-logger -->

- **Log directory not provisioned.** `/var/log/instrukt-ai/teleclaude/`
  must exist with correct permissions before any binary starts. This is
  installation's responsibility (same as v1). Binaries fail to write if
  the directory is missing — that's the right failure.

<!-- change:adopt-xdg-user-space-logger -->

- **Log directory not writable.** The log root sits under the user's XDG
  state home (`~/.local/state/instrukt-ai/teleclaude/`) and is ensured on
  first write in user space (same as v1) — no system provisioning or sudo.
  Binaries fail to write only if that path is not writable — that's the
  right failure.

<!-- /planned-change:adopt-xdg-user-space-logger -->

- **Custom log destinations bypassing observability.** If a service writes
  directly to a file or stdout outside the `tracing` macros, those lines
  don't appear in `instrukt-ai-logs` output and create a parallel log
  source. All logging goes through `tracing`.
- **Skipping `observability::init` in a binary.** No subscriber registered
  = no log output. `main` must call `init` first.

## See Also

- docs/project/design/architecture-v2/file-layout.md
  observability crate lives in the workspace.
- docs/project/design/architecture-v2/transport-rules.md
  infrastructure, used by every binary, not a service.
