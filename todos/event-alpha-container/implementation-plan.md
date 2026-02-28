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

- [ ] Define framed message format: 4-byte big-endian length prefix + UTF-8 JSON body.
- [ ] Define `AlphaRequest` dataclass:
  - `cartridge_name: str` — filename stem of the cartridge to invoke
  - `envelope: dict` — `EventEnvelope.to_stream_dict()` output
  - `catalog_snapshot: list[dict]` — serialized `EventSchema` list (no DB handle)
- [ ] Define `AlphaResponse` dataclass:
  - `envelope: dict | None` — modified envelope dict, or None if cartridge dropped it
  - `error: str | None` — exception message if the cartridge raised
  - `duration_ms: float`
- [ ] Implement `encode_message(obj: dict) -> bytes` and `decode_message(data: bytes) -> dict`.
- [ ] Implement `async read_frame(reader: asyncio.StreamReader) -> dict` and
      `async write_frame(writer: asyncio.StreamWriter, obj: dict) -> None`.
- [ ] Enforce 4 MB frame size limit: raise `FrameTooLargeError` on encode; discard on decode.

### Task 1.2: Alpha runner server

**File(s):** `teleclaude_events/alpha/runner.py`

- [ ] Define `AlphaRunner`:
  - Constructor: `socket_path: str`, `cartridges_dir: str`
  - `async start(self, shutdown_event: asyncio.Event) -> None`:
    1. Start `asyncio.start_unix_server(self._handle_client, path=socket_path)`
    2. Loop until `shutdown_event` is set; close server on shutdown
  - `async _handle_client(self, reader, writer) -> None`:
    1. Read one `AlphaRequest` frame
    2. Load cartridge module from `cartridges_dir/<cartridge_name>.py` via `importlib`
    3. Deserialize `EventEnvelope.from_stream_dict(request.envelope)`
    4. Construct a minimal `PipelineContext` (catalog rebuilt from snapshot, no DB)
    5. Call `await asyncio.wait_for(cartridge.process(envelope, ctx), timeout=10.0)`
    6. Build `AlphaResponse(envelope=result.to_stream_dict() if result else None)`
    7. Write response frame; close writer
    8. On any exception: write `AlphaResponse(envelope=None, error=str(e))`
- [ ] Cartridge loading: each request reloads from disk (no module cache). Use
      `importlib.util.spec_from_file_location` + `spec.loader.exec_module()` into a fresh
      module object. This ensures hot-reload without container restart.
- [ ] `__main__.py` entry point:
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

- [ ] Base image: `python:3.12-slim` (match daemon's Python version).
- [ ] Install only `teleclaude_events/` and its dependencies (Pydantic, aiosqlite headers
      not needed — DB is absent in the container). No `teleclaude/` code.
- [ ] Copy `teleclaude_events/` into image; `pip install -e /app/teleclaude_events`.
- [ ] `ENTRYPOINT ["python", "-m", "teleclaude_events.alpha"]`
- [ ] No `EXPOSE` (Unix socket only). No network required at build or runtime.

### Task 2.2: Container lifecycle manager

**File(s):** `teleclaude_events/alpha/container.py`

- [ ] Define `AlphaContainerManager`:
  - Constructor: `socket_path: str`, `cartridges_dir: str`, `image: str = "teleclaude-alpha-runner"`
  - `@property is_running: bool`
  - `async start(self) -> None`:
    1. Check Docker available (`which docker` or `subprocess.run(["docker", "info"])`).
       If unavailable: set `self._docker_unavailable = True`, emit
       `system.alpha-container.docker-unavailable`, return.
    2. Run container:
       ```
       docker run -d --rm --read-only --network none
         --memory 256m --cpus 0.5
         --name teleclaude-alpha-runner
         -v <codebase_root>:/repo:ro
         -v <cartridges_dir>:/alpha-cartridges:ro
         -v <socket_dir>:/run/alpha:rw          # socket lives here
         [-v <ai_creds_path>:/run/credentials/ai.json:ro]  # only if file exists
         -e ALPHA_SOCKET_PATH=/run/alpha/teleclaude-alpha.sock
         -e ALPHA_CARTRIDGES_DIR=/alpha-cartridges
         <image>
       ```
    3. Wait for socket to appear (poll up to 5 seconds, 100ms intervals). Raise on timeout.
    4. Store `self._container_id`.
  - `async stop(self) -> None`: `docker stop <container_id>` (with 5s timeout).
  - `async health_check(self) -> bool`: send a `ping` frame (empty request with
    `cartridge_name="__ping__"`); expect response within 2 seconds.
  - `async restart(self) -> None`: `stop()` then `start()`. Track restart count; after 3
    consecutive failures emit `system.alpha-container.unhealthy` and set
    `self._permanently_failed = True`.
  - `async watch_health(self, shutdown_event: asyncio.Event) -> None`:
    Loop: sleep 30s, call `health_check()`, restart if failed. Stop on `shutdown_event`.

### Task 2.3: Cartridge directory watcher

**File(s):** `teleclaude_events/alpha/container.py`

- [ ] Add `scan_cartridges(cartridges_dir: str) -> list[str]`: return list of `*.py` filenames
      (stems only) found in the directory. Returns `[]` if directory absent.
- [ ] Add `async watch_cartridges_dir(self, shutdown_event: asyncio.Event) -> None`:
  - Poll directory every 5 seconds (no `watchdog` dependency — keep deps minimal).
  - If cartridges appear when container is not running: call `start()`.
  - If cartridges disappear entirely while container is running: call `stop()`.
  - Stop on `shutdown_event`.
- [ ] Expose `has_cartridges: bool` property (cached, refreshed by watcher).

---

## Phase 3: Alpha Bridge Cartridge & Daemon Integration

### Task 3.1: Alpha bridge cartridge

**File(s):** `teleclaude_events/alpha/bridge.py`

- [ ] Define `AlphaBridgeCartridge`:
  - `name = "alpha-bridge"`
  - Constructor: `manager: AlphaContainerManager`
  - `async def process(self, event: EventEnvelope, context: PipelineContext) -> EventEnvelope | None`:
    1. If `not manager.has_cartridges` or `manager._permanently_failed` or
       `manager._docker_unavailable`: return event unchanged (zero-overhead fast path).
    2. Get list of cartridge names from `manager.scan_cartridges()`.
    3. For each cartridge name:
       a. Build `AlphaRequest(cartridge_name=name, envelope=event.to_stream_dict(), catalog_snapshot=...)`
       b. Open Unix socket connection to `manager.socket_path`.
       c. Write request frame; read response frame with `asyncio.wait_for(..., timeout=10.0)`.
       d. On timeout / connection error / `FrameTooLargeError`: log warning, append
       `{"cartridge": name, "error": "timeout/unavailable"}` to results, continue.
       e. On success: append `{"cartridge": name, "result": response.envelope}` to results.
    4. Attach all results: `event.payload["_alpha_results"] = results`.
    5. Return the (modified) event. Never return None — dropping is the approved pipeline's
       decision, not the alpha bridge's.
  - All exceptions caught at the outer level; log + return event unchanged.

### Task 3.2: Wire alpha bridge into daemon pipeline

**File(s):** `teleclaude/daemon.py`, `teleclaude_events/alpha/__init__.py`

- [ ] In `teleclaude_events/alpha/__init__.py`: export `AlphaBridgeCartridge`,
      `AlphaContainerManager`.
- [ ] In `daemon.py` startup (after existing pipeline construction):
  1. `manager = AlphaContainerManager(socket_path=..., cartridges_dir=..., image=...)`
  2. `alpha_bridge = AlphaBridgeCartridge(manager=manager)`
  3. Append `alpha_bridge` to the cartridge list (after `NotificationProjectorCartridge`).
  4. Start background tasks:
     - `asyncio.create_task(manager.watch_cartridges_dir(self.shutdown_event))`
     - `asyncio.create_task(manager.watch_health(self.shutdown_event))`
- [ ] In `daemon.py` shutdown: `await manager.stop()` before closing pipeline.
- [ ] Config: read `alpha_socket_path` and `alpha_cartridges_dir` from daemon config
      (defaults: `/tmp/teleclaude-alpha.sock` and `~/.teleclaude/alpha-cartridges/`).

### Task 3.3: System event schemas for alpha container

**File(s):** `teleclaude_events/schemas/system.py`

- [ ] Register two new schemas:
  - `system.alpha-container.unhealthy` — level: OPERATIONAL, visibility: LOCAL,
    lifecycle: creates notification, actionable: false
  - `system.alpha-container.docker-unavailable` — level: OPERATIONAL, visibility: LOCAL,
    lifecycle: creates notification, actionable: false
- [ ] Emit these via `emit_event()` from `AlphaContainerManager` (inject producer as dependency
      on construction, optional — if absent, log only).

---

## Phase 4: CLI, Tests & Quality

### Task 4.1: `telec cartridges promote` CLI command

**File(s):** `teleclaude/cli/` (new `cartridges` subcommand or extend `events`)

- [ ] `telec cartridges promote <name>` command:
  1. Resolve `~/.teleclaude/alpha-cartridges/<name>.py`.
  2. Validate file exists and is importable (syntax check via `ast.parse()`).
  3. Determine destination: prompt user for target subdirectory within
     `teleclaude_events/cartridges/` (or accept `--dest` flag).
  4. Copy file to destination.
  5. Remove from alpha cartridges directory.
  6. Print: "Promoted <name>.py → teleclaude_events/cartridges/<dest>/<name>.py\n"
     "Next: wire it into the pipeline in teleclaude/daemon.py, then commit."
- [ ] `telec cartridges list` command: list files in `~/.teleclaude/alpha-cartridges/` with
      size and modification time.

### Task 4.2: Unit tests

**File(s):** `tests/test_events/test_alpha/`

- [ ] `test_protocol.py`:
  - `encode_message` / `decode_message` round-trip
  - `FrameTooLargeError` raised for oversized messages
  - `read_frame` / `write_frame` over an in-memory pipe
- [ ] `test_bridge.py`:
  - Bridge returns event unchanged when `has_cartridges` is False (fast path)
  - Bridge returns event unchanged when `_permanently_failed` is True
  - Bridge attaches `_alpha_results` to payload on successful cartridge call
  - Bridge catches timeout and attaches error result; does not raise
  - Bridge catches connection error (container not running) gracefully
  - Bridge never returns None
- [ ] `test_container.py`:
  - `scan_cartridges` returns empty list for absent directory
  - `scan_cartridges` returns stems for `.py` files
  - `has_cartridges` reflects scan result
  - `restart` increments counter; sets `_permanently_failed` after 3 failures

### Task 4.3: Integration test (Docker-conditional)

**File(s):** `tests/test_events/test_alpha/test_integration.py`

- [ ] Skip entire module with `pytest.importorskip` or `@pytest.mark.skipif` if
      `shutil.which("docker") is None`.
- [ ] Build image (`docker build -t teleclaude-alpha-runner docker/alpha-runner/`) before test.
- [ ] Write a trivial alpha cartridge to a temp directory.
- [ ] Start `AlphaContainerManager`, send an event through `AlphaBridgeCartridge`.
- [ ] Assert `_alpha_results` present in returned envelope payload.
- [ ] Stop container; verify socket is gone.

### Task 4.4: Quality checks

- [ ] Run `make test`
- [ ] Run `make lint`
- [ ] Verify: `grep -r "from teleclaude\." teleclaude_events/alpha/` returns nothing
- [ ] Verify: container started with `--read-only --network none` (confirmed in lifecycle manager code)
- [ ] Verify no unchecked tasks remain

---

## Phase 5: Review Readiness

- [ ] Confirm all requirements reflected in code
- [ ] Confirm all tasks marked `[x]`
- [ ] Run `telec todo demo validate event-alpha-container`
- [ ] Document any deferrals in `deferrals.md`
