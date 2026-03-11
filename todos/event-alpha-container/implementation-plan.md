# Implementation Plan: event-alpha-container

## Overview

Build the alpha cartridge sandboxing layer on top of the `event-platform-core` pipeline
runtime. The work splits into four phases: (1) IPC protocol and alpha runner process that
runs inside the container, (2) the Docker image and container lifecycle manager, (3) the
in-daemon alpha bridge cartridge that integrates with the existing pipeline, and (4) the
promotion CLI command plus tests.

Codebase patterns to follow:

| Pattern              | Evidence                                                                    |
| -------------------- | --------------------------------------------------------------------------- |
| Cartridge interface  | `teleclaude_events/pipeline.py` — `Cartridge` Protocol, `PipelineContext`   |
| Background task      | `teleclaude/daemon.py` — `asyncio.create_task()` + done callback            |
| Unix socket server   | stdlib `asyncio.start_unix_server`                                          |
| Graceful shutdown    | `teleclaude/daemon.py` — `shutdown_event: asyncio.Event` passed to workers  |
| Event emit           | `teleclaude_events/producer.py` — `emit_event()`                            |
| Envelope wire format | `teleclaude_events/envelope.py` — `to_stream_dict()` / `from_stream_dict()` |

---

## Phase 1: IPC Protocol & Alpha Runner

### Task 1.1: Define IPC wire protocol

**File(s):** `teleclaude_events/alpha/protocol.py`

- [x] Define framed message format: 4-byte big-endian length prefix + UTF-8 JSON body.
- [x] Define `AlphaRequest` dataclass:
  - `cartridge_name: str` — filename stem of the cartridge to invoke
  - `envelope: dict` — `EventEnvelope.to_stream_dict()` output
  - `catalog_snapshot: list[dict]` — serialized `EventSchema` list (no DB handle)
- [x] Define `AlphaResponse` dataclass:
  - `envelope: dict | None` — modified envelope dict, or None if cartridge dropped it
  - `error: str | None` — exception message if the cartridge raised
  - `duration_ms: float`
- [x] Implement `encode_message(obj: dict) -> bytes` and `decode_message(data: bytes) -> dict`.
- [x] Implement `async read_frame(reader: asyncio.StreamReader) -> dict` and
      `async write_frame(writer: asyncio.StreamWriter, obj: dict) -> None`.
- [x] Enforce 4 MB frame size limit: raise `FrameTooLargeError` on encode; discard on decode.

### Task 1.2: Alpha runner server

**File(s):** `teleclaude_events/alpha/runner.py`

- [x] Define `AlphaRunner`:
  - Constructor: `socket_path: str`, `cartridges_dir: str`
  - `async start(self, shutdown_event: asyncio.Event) -> None`:
    1. Start `asyncio.start_unix_server(self._handle_client, path=socket_path)`
    2. Loop until `shutdown_event` is set; close server on shutdown
  - `async _handle_client(self, reader, writer) -> None`:
    1. Read one `AlphaRequest` frame
    2. **Ping handler (must be first):** if `request.cartridge_name == "__ping__"`,
       write `AlphaResponse(envelope=None, error=None, duration_ms=0)` and return.
       This prevents the health-check from falling through to disk lookup.
    3. Load cartridge module from `cartridges_dir/<cartridge_name>.py` via `importlib`
    4. Deserialize `EventEnvelope.from_stream_dict(request.envelope)`
    5. Construct a minimal `PipelineContext` (catalog rebuilt from snapshot, no DB)
    6. Call `await asyncio.wait_for(cartridge.process(envelope, ctx), timeout=10.0)`
    7. Build `AlphaResponse(envelope=result.to_stream_dict() if result else None)`
    8. Write response frame; close writer
    9. On any exception: write `AlphaResponse(envelope=None, error=str(e))`
- [x] Cartridge loading: each request reloads from disk (no module cache). Use
      `importlib.util.spec_from_file_location` + `spec.loader.exec_module()` into a fresh
      module object. This ensures hot-reload without container restart.
- [x] `__main__.py` entry point:
  ```python
  # teleclaude_events/alpha/__main__.py
  import asyncio, os
  from teleclaude_events.alpha.runner import AlphaRunner
  shutdown = asyncio.Event()
  runner = AlphaRunner(
      socket_path=os.environ["ALPHA_SOCKET_PATH"],
      cartridges_dir=os.environ["ALPHA_CARTRIDGES_DIR"],
  )
  asyncio.run(runner.start(shutdown))
  ```

---

## Phase 2: Docker Image & Container Lifecycle

### Task 2.1: Dockerfile for alpha runner

**File(s):** `docker/alpha-runner/Dockerfile`

- [x] Base image: `python:3.12-slim` (match daemon's Python version).
- [x] Install only `teleclaude_events/` and its dependencies (Pydantic, aiosqlite headers
      not needed — DB is absent in the container). No `teleclaude/` code.
- [x] Copy `teleclaude_events/` into image; `pip install -e /app/teleclaude_events`.
- [x] `ENTRYPOINT ["python", "-m", "teleclaude_events.alpha"]`
- [x] No `EXPOSE` (Unix socket only). No network required at build or runtime.

### Task 2.2: Container lifecycle manager

**File(s):** `teleclaude_events/alpha/container.py`

- [x] Define `AlphaContainerManager`:
  - Constructor: `socket_path: str`, `cartridges_dir: str`, `image: str = "teleclaude-alpha-runner"`
  - `@property is_running: bool`
  - `async start(self) -> None`: checks Docker, runs container with security flags, waits for socket.
  - `async stop(self) -> None`: `docker stop <container_id>` (with 5s timeout).
  - `async health_check(self) -> bool`: send a `ping` frame; expect response within 2 seconds.
  - `async restart(self) -> None`: `stop()` then `start()`. Track restart count; after 3
    consecutive failures emit `system.alpha-container.unhealthy` and set
    `self._permanently_failed = True`.
  - `async watch_health(self, shutdown_event: asyncio.Event) -> None`:
    Loop: sleep 30s, call `health_check()`, restart if failed. Stop on `shutdown_event`.

### Task 2.3: Cartridge directory watcher

**File(s):** `teleclaude_events/alpha/container.py`

- [x] Add `scan_cartridges(cartridges_dir: str) -> list[str]`: return list of `*.py` filenames
      (stems only) found in the directory. Returns `[]` if directory absent.
- [x] Add `async watch_cartridges_dir(self, shutdown_event: asyncio.Event) -> None`:
  - Poll directory every 5 seconds (no `watchdog` dependency — keep deps minimal).
  - If cartridges appear when container is not running: call `start()`.
  - If cartridges disappear entirely while container is running: call `stop()`.
  - Stop on `shutdown_event`.
- [x] Expose `has_cartridges: bool` property (cached, refreshed by watcher).

---

## Phase 3: Alpha Bridge Cartridge & Daemon Integration

### Task 3.1: Alpha bridge cartridge

**File(s):** `teleclaude_events/alpha/bridge.py`

- [x] Define `AlphaBridgeCartridge`:
  - `name = "alpha-bridge"`
  - Constructor: `manager: AlphaContainerManager`
  - `async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None`:
    zero-overhead fast path when no cartridges/docker_unavailable/permanently_failed.
    Per-cartridge invocation with timeout/connection/frame-too-large error handling.
    Attaches `_alpha_results` to payload. Never returns None.
  - All exceptions caught at the outer level; log + return event unchanged.

### Task 3.2: Wire alpha bridge into daemon pipeline

**File(s):** `teleclaude/daemon.py`, `teleclaude_events/alpha/__init__.py`

- [x] In `teleclaude_events/alpha/__init__.py`: export `AlphaBridgeCartridge`,
      `AlphaContainerManager`.
- [x] In `daemon.py` startup: AlphaContainerManager + AlphaBridgeCartridge registered as
      last cartridge, watch_cartridges_dir and watch_health background tasks started.
- [x] In `daemon.py` shutdown: `await manager.stop()` before closing pipeline.
- [x] Config: read `alpha_socket_path` and `alpha_cartridges_dir` from daemon config
      (defaults: `/tmp/teleclaude-alpha.sock` and `~/.teleclaude/alpha-cartridges/`).

### Task 3.3: System event schemas for alpha container

**File(s):** `teleclaude_events/schemas/system.py`

- [x] Register two new schemas:
  - `system.alpha-container.unhealthy` — level: OPERATIONAL, visibility: LOCAL,
    lifecycle: creates notification, actionable: false
  - `system.alpha-container.docker-unavailable` — level: OPERATIONAL, visibility: LOCAL,
    lifecycle: creates notification, actionable: false
- [x] Emit these via `emit_event()` from `AlphaContainerManager` (inject producer as dependency
      on construction, optional — if absent, log only).

---

## Phase 4: CLI, Tests & Quality

### Task 4.1: Extend `telec config cartridges` with alpha scope

**File(s):** `teleclaude/cli/cartridge_cli.py`, `teleclaude_events/lifecycle.py`

- [x] Add `CartridgeScope.alpha` to the `CartridgeScope` enum in `lifecycle.py`.
- [x] `telec config cartridges list --scope alpha` command: lists ~/.teleclaude/alpha-cartridges/
- [x] `telec config cartridges promote --from alpha --to domain --domain <name> --id <name>`:
      syntax-checks file, copies to domain cartridges dir, removes from alpha dir.

### Task 4.2: Unit tests

**File(s):** `tests/unit/test_alpha/`

- [x] `test_protocol.py`: round-trip, FrameTooLargeError, read_frame/write_frame
- [x] `test_bridge.py`: all 6 behavioral contracts (fast path, permanently_failed,
      alpha_results on success, timeout isolation, connection error isolation, never None)
- [x] `test_container.py`: scan_cartridges absent dir, stems, has_cartridges, restart counter

### Task 4.3: Integration test (Docker-conditional)

**File(s):** `tests/integration/test_alpha_integration.py`

- [x] Skip entire module if `shutil.which("docker") is None`.
- [x] Build image before test, write trivial cartridge, start manager, run through bridge.
- [x] Assert `_alpha_results` present. Stop container.

### Task 4.4: Quality checks

- [x] Run `make test` — 14 passed, 1 skipped (Docker integration skipped on no-Docker env)
- [x] Run `make lint` — no new failures (pre-existing module size violations unchanged)
- [x] Verify: `grep -r "from teleclaude\." teleclaude_events/alpha/` returns nothing
- [x] Verify: container started with `--read-only --network none` (confirmed in lifecycle manager code)
- [x] Verify no unchecked tasks remain

---

## Phase 5: Review Readiness

- [x] Confirm all requirements reflected in code
- [x] Confirm all tasks marked `[x]`
- [x] Run `telec todo demo validate event-alpha-container` — 6 executable blocks found
- [x] Demo artifact: `demos/event-alpha-container/demo.md` promoted
- [x] No deferrals needed
