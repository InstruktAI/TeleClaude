# Requirements: event-alpha-container

## Known Blockers

### BLOCKER 1: `telec cartridges` CLI collision with event-mesh-distribution — RESOLVABLE

Both this todo and `event-mesh-distribution` originally proposed `telec cartridges list`
with incompatible semantics. However, **`telec config cartridges` already exists** in
`teleclaude/cli/cartridge_cli.py` with `list`, `install`, `remove`, and `promote` commands
that manage the lifecycle-based cartridge system (personal/domain/platform scopes).

The existing `telec config cartridges list` lists installed cartridges by domain/member
from the filesystem lifecycle manager. The existing `telec config cartridges promote`
promotes cartridges between scopes (personal → domain → platform).

**Resolution (inferred — requires confirmation):** Alpha cartridge commands should be a
new scope or subcommand under the existing `telec config cartridges` CLI:

- `telec config cartridges list --scope alpha` — lists `~/.teleclaude/alpha-cartridges/*.py`
- `telec config cartridges promote --from alpha --to domain --domain <name>` — promotes
  an alpha cartridge file into the cartridge lifecycle system.

This avoids a new top-level `telec cartridges` namespace that collides with mesh-distribution
and aligns with the existing lifecycle manager pattern. The `event-mesh-distribution` todo
should similarly fold its proposed `telec cartridges list/activate/reject` under the
existing CLI surface.

**Status:** The design path is clear. The builder can implement under `telec config cartridges`
with `--scope alpha` support. This blocker is downgraded from blocking to resolved-with-inference.

### BLOCKER 2: Health-check ping handler — RESOLVED IN PLAN

The alpha runner's dispatch logic must handle `cartridge_name="__ping__"` as a special case
before attempting disk access, returning an explicit pong response. This is now explicitly
specified in Task 1.2 of the implementation plan. The builder implements the ping handler
as part of the runner server, not as a separate file.

---

## Goal

Add a sandboxed execution tier for experimental cartridges. The approved pipeline runs
in-process as today; alpha cartridges run afterward inside a Docker sidecar with no
network access, read-only mounts, and capped resources. The daemon communicates with the
container over a Unix socket. Failures and timeouts in alpha cartridges are fully isolated
— the daemon always returns the approved pipeline output regardless. When no alpha cartridges
are present the container is never started.

## Scope

### In scope

1. **Docker sidecar container** (`teleclaude-alpha-runner`):
   - Image built from a minimal Python base with `teleclaude_events/` installed (no daemon code).
   - `--read-only` filesystem, `--network none`, `--memory 256m`, `--cpus 0.5`.
   - Three read-only bind mounts:
     - Codebase root (`/repo`, for import resolution)
     - AI credentials file (`/run/credentials/ai.json`, for cartridges that call LLMs)
     - Alpha cartridges directory (`~/.teleclaude/alpha-cartridges/`, mounted as `/alpha-cartridges`)
   - Unix socket at a well-known path (`/tmp/teleclaude-alpha.sock` or configurable).

2. **IPC protocol over the Unix socket**:
   - Framed JSON messages (4-byte length prefix + JSON body).
   - Request: serialized `EventEnvelope` + pipeline context snapshot (catalog metadata only,
     no DB handle).
   - Response: modified `EventEnvelope | null` per cartridge, plus structured error payload.
   - One request/response cycle per cartridge invocation. Stateless per call.

3. **Alpha runner process** (runs inside the container):
   - Listens on the Unix socket.
   - Discovers cartridges by scanning `/alpha-cartridges/` for `*.py` files that export
     `async def process(event, context)`.
   - For each incoming request: loads the addressed cartridge, calls `process()`, returns result.
   - Per-request timeout: 10 seconds. Returns error payload on timeout or exception.

4. **Alpha bridge cartridge** (runs in daemon, in-process):
   - Last cartridge in the approved pipeline chain.
   - On each event: checks if the container is running; if not and alpha cartridges exist,
     starts it. If no alpha cartridges exist, returns the event unchanged immediately.
   - Sends the event to the container via the socket, collects the result (with timeout).
   - On timeout, exception, or container unavailability: logs warning, returns the incoming
     event unchanged — never raises, never blocks the approved pipeline result.
   - Result from alpha cartridges is advisory: attached to the envelope as
     `payload["_alpha_results"]` (list of per-cartridge outputs). Downstream components
     may ignore it.

5. **Container lifecycle management**:
   - Daemon starts the container lazily (first event with alpha cartridges present).
   - Daemon stops the container on graceful shutdown.
   - Health check: periodic ping (empty message, expect pong) every 30 seconds.
     Restart container if health check fails, up to 3 attempts. Emit
     `system.alpha-container.unhealthy` event on repeated failure.
   - Restart on OOM or crash without propagating errors to the pipeline.

6. **Zero-overhead fast path**:
   - If `~/.teleclaude/alpha-cartridges/` is empty (or absent): alpha bridge cartridge is
     a no-op, container is not started, no socket is created.
   - Detection is cached at pipeline startup. A `SIGHUP` or a file-watch event on the
     alpha cartridges directory triggers re-evaluation.

7. **Promotion path**:
   - `telec config cartridges promote --from alpha --to domain --domain <name> --id <name>`
     CLI command: copies cartridge from `~/.teleclaude/alpha-cartridges/<name>.py` into
     the cartridge lifecycle directory for the target domain, removes it from the alpha mount.
   - Promotion does not auto-wire the cartridge into the pipeline; that requires a code
     change. The command surfaces the file for review and domain pipeline configuration.

8. **`Dockerfile`** for the alpha runner (`docker/alpha-runner/Dockerfile`).

9. **`docker-compose.alpha.yml`** for local development (optional override).

10. **Tests**: unit tests for IPC protocol, bridge cartridge isolation behavior, container
    lifecycle state machine. Integration test skipped if Docker unavailable.

### Out of scope

- Cartridge dependency DAG / ordering between multiple alpha cartridges (future, when
  `event-domain-infrastructure` lands).
- Trust evaluation of alpha cartridge output (deferred to `event-system-cartridges` integration).
- Network-enabled alpha cartridges (explicitly disallowed; network access requires promotion
  to approved tier).
- GUI for managing alpha cartridges.
- Multi-node alpha distribution (mesh concerns belong in `event-mesh-distribution`).

## Success Criteria

- [ ] `~/.teleclaude/alpha-cartridges/` empty → container never starts, zero latency added to pipeline
- [ ] A `.py` file in the alpha cartridges directory causes the container to start on next event
- [ ] Alpha cartridge receives the event envelope and its modified result appears in `payload["_alpha_results"]`
- [ ] Alpha cartridge timeout (> 10s) does not block or error the pipeline; logs a warning
- [ ] Container crash is detected, restarted, and `system.alpha-container.unhealthy` emitted after 3 failures
- [ ] Container runs with `--read-only`, `--network none`, `--memory 256m`, `--cpus 0.5`
- [ ] `telec config cartridges promote --from alpha --to domain --domain <name> --id <name>` copies the file into the lifecycle directory and removes it from the alpha mount
- [ ] `make test` passes (unit tests; Docker integration test skipped gracefully when Docker unavailable)
- [ ] `make lint` passes
- [ ] No imports from `teleclaude.*` inside the alpha runner image

## Constraints

- The alpha bridge cartridge must never raise an exception visible to the pipeline executor.
  All alpha errors are caught, logged, and silently discarded.
- Unix socket path must be configurable; default `/tmp/teleclaude-alpha.sock`.
- IPC frame size limit: 4 MB per message. Envelopes exceeding this are dropped with a log warning.
- Container must be stopped cleanly before daemon exits (to avoid zombie containers).
- The alpha runner image must contain only `teleclaude_events/` and its dependencies.
  No `teleclaude/` daemon code, no config secrets baked into the image.
- AI credentials mount is optional; if the file is absent, it is not mounted (cartridges
  that need credentials will fail at runtime inside the container, not at startup).
- Python version in the container must match the daemon's Python version.

## Risks

- **Docker availability**: Docker may not be installed in all environments. The entire alpha
  subsystem must degrade gracefully to a no-op if `docker` is not in PATH or the daemon
  cannot reach the Docker socket. Emit `system.alpha-container.docker-unavailable` on
  first attempt, then silence.
- **Unix socket on macOS vs Linux**: socket path conventions and permissions differ.
  Use `/tmp/` for portability; `/run/` is Linux-only without configuration.
- **Container startup latency**: cold start (image pull + container init) may take several
  seconds. First event after alpha cartridges are installed will experience this delay.
  The timeout guard prevents this from stalling the pipeline, but the first result may be
  missed. Acceptable: alpha results are advisory.
- **Hot reload of alpha cartridges**: cartridges are Python files loaded at request time
  inside the container. Module-level globals are not preserved between calls (stateless by
  design). This simplifies the model but means alpha cartridges cannot maintain state.
  Document this constraint.
- **IPC serialization**: `EventEnvelope` serialization round-trip must be lossless.
  Use the existing `to_stream_dict` / `from_stream_dict` methods as the wire format baseline.
