# Demo: event-alpha-container

## Validation

```bash
# Verify alpha cartridges directory exists (or is absent — zero-overhead path)
ls -la ~/.teleclaude/alpha-cartridges/ 2>/dev/null || echo "No alpha cartridges directory — expected for zero-overhead"
```

```bash
# Verify Docker image exists
docker images teleclaude-alpha-runner --format '{{.Repository}}:{{.Tag}} {{.Size}}'
```

```bash
# Verify no daemon code leaks into the alpha runner image
docker run --rm teleclaude-alpha-runner python -c "import teleclaude" 2>&1 | grep -q "ModuleNotFoundError" && echo "PASS: no teleclaude imports in alpha runner" || echo "FAIL: teleclaude module found in alpha runner"
```

```bash
# Verify container security flags
docker inspect teleclaude-alpha-runner 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
if data:
    hc = data[0].get('HostConfig', {})
    print(f'ReadonlyRootfs: {hc.get(\"ReadonlyRootfs\", False)}')
    print(f'NetworkMode: {hc.get(\"NetworkMode\", \"unknown\")}')
    print(f'Memory: {hc.get(\"Memory\", 0) // (1024*1024)}MB')
    print(f'NanoCpus: {hc.get(\"NanoCpus\", 0) / 1e9} CPUs')
" 2>/dev/null || echo "Container not running — inspect skipped"
```

```bash
# Run unit tests for alpha subsystem
make test -- tests/test_events/test_alpha/ -v 2>&1 | tail -20
```

```bash
# Verify alpha CLI commands exist
telec config cartridges list --scope alpha 2>&1
```

## Guided Presentation

### Step 1: Zero-overhead fast path (no alpha cartridges)

Verify the alpha subsystem adds zero latency when no alpha cartridges exist. The alpha
bridge cartridge is a no-op, the container is never started, no socket is created.

1. Ensure `~/.teleclaude/alpha-cartridges/` is empty or absent.
2. Trigger an event through the pipeline (any event).
3. Observe in daemon logs: no alpha-related log lines, no Docker activity.
4. **Why it matters:** The alpha subsystem must be invisible when unused.

### Step 2: Alpha cartridge triggers container startup

Place a trivial alpha cartridge and observe lazy container startup.

1. Create `~/.teleclaude/alpha-cartridges/echo_alpha.py`:
   ```python
   async def process(event, context):
       event.payload["_echo"] = "alpha processed"
       return event
   ```
2. Trigger an event through the pipeline.
3. Observe: container starts (`docker ps` shows `teleclaude-alpha-runner`), the event
   passes through the alpha bridge, `_alpha_results` appears in the payload.
4. **Why it matters:** Lazy startup means zero cost until needed, then automatic.

### Step 3: Isolation verification

Verify the container runs in a secure sandbox: read-only filesystem, no network, capped
resources.

1. `docker inspect teleclaude-alpha-runner` — confirm `ReadonlyRootfs`, `NetworkMode: none`,
   `Memory: 268435456` (256MB), `NanoCpus: 500000000` (0.5 CPU).
2. Attempt a network call from inside: `docker exec teleclaude-alpha-runner curl http://example.com` — must fail.
3. **Why it matters:** Alpha cartridges are untrusted; isolation is the security boundary.

### Step 4: Failure isolation

Verify alpha cartridge failures do not propagate to the approved pipeline.

1. Create a crashing cartridge `~/.teleclaude/alpha-cartridges/crasher.py`:
   ```python
   async def process(event, context):
       raise RuntimeError("intentional crash")
   ```
2. Trigger an event.
3. Observe: the pipeline returns the event unchanged (approved result), the `_alpha_results`
   contains an error entry for `crasher`, no exception propagated.
4. **Why it matters:** Alpha failures are advisory, never blocking.

### Step 5: Health check and container lifecycle

Verify the health check detects failures and the restart logic works.

1. Kill the runner process inside the container: `docker exec teleclaude-alpha-runner kill 1`.
2. Wait 30 seconds for the health check ping to fire.
3. Observe: container restarts automatically (daemon logs show restart).
4. Kill it 3 more times. After 3 consecutive failures: `system.alpha-container.unhealthy`
   event emitted, container marked permanently failed.
5. **Why it matters:** Self-healing with a circuit breaker prevents infinite restart loops.

### Step 6: Promotion path

Promote an alpha cartridge into the lifecycle system.

1. `telec config cartridges promote --from alpha --to domain --domain system --id echo_alpha`
2. Verify: `~/.teleclaude/alpha-cartridges/echo_alpha.py` is gone.
3. Verify: the file now exists in the domain cartridge directory.
4. **Why it matters:** Promotion is the upgrade path from experimental to approved.
