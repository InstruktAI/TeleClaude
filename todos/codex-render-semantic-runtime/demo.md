# Demo: codex-render-semantic-runtime

## Medium

CLI + log inspection + test output. This is a runtime/architecture refactor with no
user-facing UI changes. The demo proves behavioral parity and performance improvement
through observable metrics and test evidence.

## Validation

```bash
# Semantic parity: Codex render-derived synthetic events still behave the same.
pytest -q tests/unit/test_codex_replay.py tests/unit/test_polling_coordinator.py
```

```bash
# Runtime behavior: wake-driven capture, adaptive cadence, and session runtime.
pytest -q tests/unit/test_session_runtime.py
```

```bash
# Bridge/runtime guardrails: capture budget split and teardown cleanup.
pytest -q tests/unit/test_output_poller.py tests/unit/test_session_cleanup.py
```

```bash
# Control lane: compound controls queue, plain keys remain direct.
pytest -q tests/unit/test_session_control_queue.py
```

```bash
# Full suite: everything passes.
make test
```

```bash
# Structural validation of the demo artifact itself.
telec todo demo validate codex-render-semantic-runtime
```

## Guided Presentation

### Step 1: Prove the capture budget is fixed

Show that line lookback and UI char budget are now separate constants:

```bash
grep -n 'CAPTURE_PANE_LOOKBACK_LINES\|UI_MESSAGE_MAX_CHARS' teleclaude/constants.py
```

Verify `capture_pane()` uses the dedicated lookback constant:

```bash
grep -n 'CAPTURE_PANE_LOOKBACK_LINES' teleclaude/core/tmux_bridge.py
```

### Step 2: Prove session teardown cleans tmp dirs

Verify the teardown path removes per-session tmp directories:

```bash
pytest -v tests/unit/test_session_cleanup.py -k "tmp"
```

### Step 3: Prove the Codex semantic contract still holds

Run the Codex render-semantics replay tests. Observe that rendered snapshots still
produce the expected synthetic `tool_use`, `tool_done`, and `user_prompt_submit`
behavior. Confirm that `agent_stop` remains hook-authoritative and is not synthesized
by the render lane.

```bash
pytest -v tests/unit/test_codex_replay.py
```

### Step 4: Show the three-lane extraction

Verify Codex render semantics live in a dedicated module, separate from the polling
coordinator:

```bash
wc -l teleclaude/core/codex_render_semantics.py teleclaude/core/polling_coordinator.py
```

The render-semantic module should contain all parser functions. The polling coordinator
should only contain orchestration and metrics.

### Step 5: Show that idle sessions are no longer polled blindly

Run the runtime behavior tests. Observe that idle sessions back off capture frequency
and that wake signals reactivate fast capture when output becomes meaningful again.

```bash
pytest -v tests/unit/test_session_runtime.py -k "cadence"
```

### Step 6: Show the control-lane split

Exercise compound control actions through the control queue tests. Observe that plain
keys remain direct, while delayed text-injection actions can report queued or dispatched
status without blocking the caller on the tmux bridge sleep.

```bash
pytest -v tests/unit/test_session_control_queue.py
```

### Step 7: Explain why this matters

The system still uses tmux as the canonical session substrate, preserving restart-safe
continuity. Codex keeps its render-derived live observability. The difference is that
runtime cost now scales with actual session activity instead of constant blind polling.
The three-lane model (hook, render, transcript) makes responsibilities explicit instead
of mixing them inside one poll loop.
