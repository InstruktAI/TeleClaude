# Implementation Plan: codex-render-semantic-runtime

## Overview

Refactor session output observation from a monolithic fixed-rate polling loop into
a render-aware session runtime with explicit observability lanes, adaptive cadence,
and separated control concerns.

The plan is structured in six phases: Immediate Corrections (safe fixes first),
Replay Corpus (semantic safety net), Render-Aware Runtime (structural extraction
and runtime actor), Wake-Driven Capture (adaptive cadence), Ephemeral Control Lane,
and Validation.

The canonical live semantic source for Codex remains `capture-pane` snapshots;
`pipe-pane` is a wake signal, not a replacement.

---

## Phase 1: Immediate Corrections

Safe fixes with no semantic behavior changes. Each task produces a commit that
passes all existing tests.

### Task 1.1: Fix capture budget regression

**What:** Split the UI character budget (`UI_MESSAGE_MAX_CHARS = 3900`) from tmux
`capture-pane` line lookback. Add a dedicated `CAPTURE_PANE_LOOKBACK_LINES` constant
and use it as the default in `tmux_bridge.capture_pane()`.

Current code at `tmux_bridge.py:1031`:
```python
window_lines = capture_lines if isinstance(capture_lines, int) and capture_lines > 0 else UI_MESSAGE_MAX_CHARS
```
The fix:
```python
from teleclaude.constants import CAPTURE_PANE_LOOKBACK_LINES
window_lines = capture_lines if isinstance(capture_lines, int) and capture_lines > 0 else CAPTURE_PANE_LOOKBACK_LINES
```

**Why:** The current code uses a 3900-char budget as a line count for `-S -3900`,
requesting ~3900 lines of scrollback from tmux. This is a type confusion: character
budgets and line counts are different units. Terminal panes rarely exceed 200-500
visible lines. The Codex semantic parser's deepest lookback is
`CODEX_TOOL_ACTION_LOOKBACK_LINES = 120` lines. The regression inflates every
`capture-pane` subprocess with unnecessary scrollback, increasing tmux CPU and memory
pressure across all 27+ concurrent sessions. 500 lines provides generous margin above
the parser's 120-line lookback. Fixing this is zero-risk, high-impact, and must land
before the runtime refactor to establish a clean baseline.

**Verification:**
- [ ] `CAPTURE_PANE_LOOKBACK_LINES` exists in `constants.py`, distinct from `UI_MESSAGE_MAX_CHARS`
- [ ] `tmux_bridge.capture_pane()` uses `CAPTURE_PANE_LOOKBACK_LINES` as default
- [ ] Existing Codex semantic tests pass (parser sees enough scrollback)
- [ ] Test: assert `capture_pane` default lookback is `CAPTURE_PANE_LOOKBACK_LINES`, not `UI_MESSAGE_MAX_CHARS`

**Referenced files:**
- `teleclaude/constants.py` — add `CAPTURE_PANE_LOOKBACK_LINES = 500`
- `teleclaude/core/tmux_bridge.py` — update `capture_pane` default (line 1031)

### Task 1.2: Enrich session teardown with per-session tmp cleanup

**What:** Add removal of `~/.teleclaude/tmp/sessions/{safe_id}` to the existing
`cleanup_session_resources()` flow in `session_cleanup.py`.

Export `_get_session_tmp_basedir` and `_safe_path_component` from `tmux_bridge` as
public functions (`get_session_tmp_basedir`, `safe_path_component`). Compute the
per-session path in `cleanup_session_resources` and `shutil.rmtree` it after the
existing workspace cleanup.

Add `cleanup_orphan_tmp_dirs()` that sweeps abandoned tmp dirs for sessions no longer
in the database, following the existing `cleanup_orphan_workspaces()` pattern.

**Why:** 1932 accumulated temp directories prove that teardown does not clean
per-session tmp trees. The cleanup logic in `cleanup_session_resources()` already
removes workspace dirs; extending it to also remove session tmp dirs is the natural
integration point (requirement 7). Creating a separate cleanup system would violate
the single-lifecycle principle.

**Verification:**
- [ ] `cleanup_session_resources()` removes the per-session tmp directory
- [ ] `get_session_tmp_basedir()` and `safe_path_component()` are public functions
- [ ] Test: teardown removes tmp dir when it exists
- [ ] Test: teardown handles missing tmp dir gracefully
- [ ] `cleanup_orphan_tmp_dirs()` sweeps abandoned tmp dirs

**Referenced files:**
- `teleclaude/core/session_cleanup.py` — add tmp dir removal + orphan sweep
- `teleclaude/core/tmux_bridge.py` — rename private functions to public
- `tests/unit/test_session_cleanup.py` — add tests

### Task 1.3: Cheapen the current hot loop

**What:** Remove redundant per-tick `session_exists()` call in `OutputPoller.poll()`.
Currently the loop calls `session_exists()` (line 138) then `capture_pane()` (line 199)
every tick — two tmux subprocess calls where one suffices.

Change: infer session liveness from `capture_pane()` return. If capture succeeds, the
session exists. If capture returns empty string with a non-zero return code (the bridge
logs and returns ""), check session health on a slower cadence (every 5 iterations).
Move `is_pane_dead()` check to the same slower cadence.

**Why:** Both `session_exists()` and `capture_pane()` spawn tmux subprocesses. With
27+ sessions at 1.0s cadence, eliminating the redundant pre-check halves per-tick tmux
subprocess count from ~54/s to ~27/s immediately. The session death watchdog still
detects disappearances within 5 seconds (5 iterations × 1s), which is acceptable since
the existing code only detected death on the next 1s tick anyway. The requirements
explicitly state "Tests no longer depend on the old assumption that `session_exists()`
must run before every `capture-pane` call."

**Verification:**
- [ ] `session_exists()` is NOT called every poll iteration
- [ ] Session death still detected within 5 seconds (from capture failure + health check)
- [ ] `is_pane_dead()` runs every 5 iterations or on capture failure
- [ ] Existing tests updated: no assertion that `session_exists` runs per-tick
- [ ] No semantic regression: Codex events emit correctly

**Referenced files:**
- `teleclaude/core/output_poller.py` — restructure main loop health checks
- `tests/unit/test_output_poller.py` — update health check assertions

---

## Phase 2: Replay Corpus and Semantic Baseline

### Task 2.1: Scaffold Codex replay fixture corpus

**What:** Create `tests/fixtures/codex_pane_snapshots/` with synthetic pane captures
modeled on real Codex terminal output patterns. Each fixture is a raw string with ANSI
codes intact (as `capture_pane -e` returns).

Fixtures covering key states:
- `startup_prompt.txt` — fresh session, `›` prompt visible near bottom
- `typing_partial.txt` — user mid-typing, partial text after `›`
- `spinner_active.txt` — agent spinner/status line (e.g., `◦ Working...`)
- `tool_action_read.txt` — tool action visible (e.g., dim `• Read src/main.py`)
- `tool_done_prompt.txt` — tool completed, prompt reappeared
- `compact_fast_turn.txt` — compact dimmed boundary (e.g., dim `• hi`)
- `stale_scrollback.txt` — stale scrollback with old prompt far above live bottom
- `seeded_prompt.txt` — prompt buffer pre-seeded from dispatch, snapshot lacks visible text

**Why:** The existing Codex semantic parser tests use synthetic inline strings, not
captured pane snapshots. Without a fixture corpus, the code extraction in Phase 3 risks
changing subtle timing or scrollback handling without detection. The corpus establishes
the semantic baseline that all subsequent changes must preserve.

**Verification:**
- [ ] `tests/fixtures/codex_pane_snapshots/` contains at least 8 fixtures
- [ ] Each fixture includes ANSI codes for styling detection tests
- [ ] Fixtures cover all key semantic states listed above

**Referenced files:**
- `tests/fixtures/codex_pane_snapshots/` — create directory + fixture files

### Task 2.2: Add parser replay tests

**What:** Write `tests/unit/test_codex_replay.py` that feeds fixture snapshots through
the Codex semantic parser functions and asserts expected synthetic events.

Tests cover:
- `_extract_prompt_block()` extracts correct input from `typing_partial.txt`
- `_has_live_prompt_marker()` returns True for `startup_prompt.txt`, False for
  `spinner_active.txt`
- `_find_recent_tool_action()` finds action in `tool_action_read.txt`
- `_is_live_agent_responding()` returns True for `spinner_active.txt`
- `_is_compact_dimmed_agent_boundary_line()` triggers on dimmed lines in
  `compact_fast_turn.txt`
- Stale scrollback suppression on `stale_scrollback.txt`
- Full sequence: typing → submit → tool_use → tool_done → prompt returns
  emits expected synthetic events in order
- `agent_stop` is NOT synthesized (hook-authoritative invariant)
- Seeded prompt takes precedence over shorter visible snapshot

**Why:** These tests are the safety net for Phase 3. They prove which synthetic events
each snapshot sequence produces. After extraction, the same tests (with updated
imports) must produce identical results.

**Verification:**
- [ ] Replay tests pass against current parser code (pre-refactor baseline)
- [ ] Tests cover tool_use, tool_done, user_prompt_submit emission
- [ ] Tests cover stale scrollback suppression, seeded prompt, no synthetic agent_stop
- [ ] Tests structured for re-run after extraction (import paths parameterized)

**Referenced files:**
- `tests/unit/test_codex_replay.py` — create
- `tests/fixtures/codex_pane_snapshots/` — fixture source
- `teleclaude/core/polling_coordinator.py` — import target (pre-extraction)

---

## Phase 3: Render-Aware Session Runtime

### Task 3.1: Extract Codex render semantics into dedicated module

**What:** Create `teleclaude/core/codex_render_semantics.py` by moving all
Codex-specific parsing, state, and event synthesis out of `polling_coordinator.py`.

Move these items (listed with current line ranges):
- Constants: `CODEX_INPUT_MAX_CHARS` (43), `CODEX_PROMPT_MARKER` (46),
  `CODEX_PROMPT_LIVE_DISTANCE` (47), `CODEX_TOOL_ACTION_LOOKBACK_LINES` (48),
  `CODEX_AGENT_MARKERS` (50-69), `_ANSI_SGR_RE` (71), `_ANSI_BOLD_TOKEN_RE` (72),
  `_ACTION_WORD_RE` (73), `_TREE_CONTINUATION_PREFIX_RE` (74),
  `_CODEX_TOOL_ACTION_WORDS` (77-94)
- ANSI helpers: `_strip_ansi` (97), `_has_sgr_param` (102), `_is_suggestion_styled`
  (111), `_strip_suggestion_segments` (116)
- Parser functions: `_extract_prompt_block` (288), `_find_prompt_input` (365),
  `_has_agent_marker` (371), `_has_live_prompt_marker` (381),
  `_is_live_agent_marker_line` (398), `_is_compact_dimmed_agent_boundary_line` (414),
  `_find_recent_tool_action` (437), `_is_live_agent_responding` (483)
- State classes: `CodexInputState` (147), `CodexTurnState` (163)
- Per-session state dicts: `_codex_input_state` (174), `_codex_turn_state` (175)
- Event synthesis: `_emit_synthetic_codex_event` (489),
  `_maybe_emit_codex_turn_events` (523), `_maybe_emit_codex_input` (612),
  `seed_codex_prompt_from_message` (257), `_mark_codex_turn_started` (248),
  `_cleanup_codex_input_state` (727)

Keep in `polling_coordinator.py`:
- `poll_and_send_output()` orchestration loop
- Output metrics: `OutputMetricsState`, `_record_output_tick`, `_clear_output_metrics`
- Polling registration: `_active_pollers`, `schedule_polling`, `_register_polling`,
  `_unregister_polling`, `is_polling`, `_handle_background_poller_result`

Update `polling_coordinator.py` to import from the new module. Re-export
`seed_codex_prompt_from_message` for backward-compatible access from
`command_handlers.py`.

**Why:** `polling_coordinator.py` is ~1000 lines mixing polling orchestration with
Codex-specific semantic inference. The extraction makes the three-lane model explicit
in code structure: the render lane (Codex semantics) is now a standalone module that
the session runtime can invoke independently. Without this separation, the runtime
refactor would deepen existing coupling and make the module harder to test, review,
and maintain.

**Verification:**
- [ ] All Codex parser functions live in `codex_render_semantics.py`
- [ ] `polling_coordinator.py` imports and calls into the new module
- [ ] All `test_polling_coordinator.py` tests pass (updated imports)
- [ ] Replay tests from Task 2.2 pass against the extracted module
- [ ] `agent_stop` is NOT synthesized by the render-semantic module
- [ ] No behavioral change: same inputs produce same synthetic events

**Referenced files:**
- `teleclaude/core/codex_render_semantics.py` — create
- `teleclaude/core/polling_coordinator.py` — remove moved code, add imports
- `teleclaude/core/command_handlers.py` — verify `seed_codex_prompt_from_message` import
- `tests/unit/test_polling_coordinator.py` — update imports
- `tests/unit/test_codex_replay.py` — update imports to extracted module

### Task 3.2: Introduce SessionRuntime actor

**What:** Create `teleclaude/core/session_runtime.py` with a `SessionRuntime` dataclass
that owns per-session state currently scattered across module-level dicts.

`SessionRuntime` fields:
- `session_id: str`
- `tmux_session_name: str`
- `codex_input: CodexInputState` — prompt detection state (from `codex_render_semantics`)
- `codex_turn: CodexTurnState` — turn/tool event state
- `metrics: OutputMetricsState` — observability metrics (from `polling_coordinator`)
- `cadence: CadenceState` — active/idle/audit cadence (new, Task 4.2)
- `wake_dirty: bool` — wake signal flag (new, Task 4.1)
- `active_agent: str | None` — cached for semantic dispatch

`SessionRuntimeRegistry`:
- `_active_runtimes: dict[str, SessionRuntime]` — replaces the three separate dicts
- `get_or_create(session_id, ...) -> SessionRuntime`
- `cleanup(session_id)` — replaces `_cleanup_codex_input_state` + `_clear_output_metrics`

Update `polling_coordinator.py`:
- `poll_and_send_output()` creates a runtime via the registry at start
- Pass runtime state to `_maybe_emit_codex_turn_events()` and `_maybe_emit_codex_input()`
  instead of letting them look up module-level dicts
- Finally block cleans up runtime via registry

**Why:** The current module-level dicts (`_codex_input_state`, `_codex_turn_state`,
`_output_metrics_state`) have no structural relationship. State for a session is spread
across three separate dicts keyed by `session_id`. This makes cleanup error-prone (must
clean all three), prevents reasoning about session state holistically (e.g., "is this
session idle enough to slow down?"), and couples the polling coordinator to
Codex-specific concerns. A per-session runtime actor provides clean ownership,
lifecycle-aligned cleanup, and a natural home for cadence and wake logic.

**Verification:**
- [ ] `SessionRuntime` dataclass exists with all fields listed
- [ ] `SessionRuntimeRegistry` replaces module-level state dicts
- [ ] `poll_and_send_output()` creates/uses runtime from registry
- [ ] Cleanup in finally block handles all state as a unit
- [ ] All existing `test_polling_coordinator.py` tests pass

**Referenced files:**
- `teleclaude/core/session_runtime.py` — create
- `teleclaude/core/polling_coordinator.py` — use registry, pass state explicitly
- `teleclaude/core/codex_render_semantics.py` — functions accept state params
- `tests/unit/test_session_runtime.py` — create with basic lifecycle tests

---

## Phase 4: Wake-Driven Capture and Adaptive Cadence

### Task 4.1: Add wake/dirty signal via pipe-pane

**What:** When a `SessionRuntime` starts for a Codex session, attach `pipe-pane -o` to
the tmux session. The pipe target writes to a per-session FIFO in the session's tmp dir.
An asyncio coroutine monitors the FIFO and sets `runtime.wake_dirty = True` when bytes
arrive.

On startup, reconnect, headless tmux adoption/bootstrap, and audit-triggered drift
recovery, take an explicit reconciliation snapshot because `pipe-pane -o` is prospective
(does not replay already-rendered content, confirmed by local probe). The runtime/docs
must make lane authority explicit for these transitions: hook lane for authoritative
native lifecycle events, render lane for the live pane snapshot that re-establishes
semantic truth, transcript lane for durable backfill only.

Cleanup: `stop_pipe_pane()` on session teardown. The FIFO is removed with the tmp dir
cleanup from Task 1.2.

**Why:** The current poll loop captures rendered snapshots on every tick regardless of
session activity. `pipe-pane -o` provides a lightweight signal that output bytes flowed
since the last check. By gating `capture-pane` on wake signals (plus periodic audit),
idle sessions can skip most captures entirely. The input.md confirms `pipe-pane` is
suitable for "something changed" detection but not as a semantic source.

**Verification:**
- [ ] `pipe-pane -o` attached on poller start for Codex sessions
- [ ] `pipe-pane` detached on poller stop
- [ ] `wake_dirty` flag set when pipe output detected
- [ ] Immediate reconciliation snapshot on startup/reconnect/headless bootstrap
- [ ] Audit-triggered drift recovery re-enters the reconciliation snapshot path
- [ ] Test: simulated pipe output sets dirty flag
- [ ] Test: revived headless session triggers the same initial render reconciliation path

**Referenced files:**
- `teleclaude/core/session_runtime.py` — add wake signal handling
- `teleclaude/core/tmux_bridge.py` — reuse existing `start_pipe_pane`, `stop_pipe_pane`
- `teleclaude/core/tmux_io.py` — headless revive path must trigger runtime reconciliation
- `teleclaude/core/command_handlers.py` — headless adoption path must trigger runtime reconciliation
- `tests/unit/test_session_runtime.py` — add wake signal tests
- `tests/unit/test_command_handlers.py` — extend headless adoption coverage

### Task 4.2: Adaptive cadence state machine

**What:** Add `CadenceState` to `SessionRuntime` with three modes and transition logic.
Replace the fixed `poll_interval` in `OutputPoller.poll()` with
`runtime.current_cadence_s`.

`CadenceState` modes:
- **Fast** (`cadence_fast_s`, default 0.5s): active turns, startup, reconnect,
  recent user input, recent wake signal
- **Slow** (`cadence_slow_s`, default 5.0s): no wake for `idle_transition_s` (10s)
- **Audit** (`cadence_audit_s`, default 30.0s): periodic reconciliation, fires
  independently of mode

Transitions:
- fast → slow: no wake signal for `idle_transition_s`
- slow → fast: wake signal, user input, or explicit poll trigger
- audit fires on timer regardless of current mode

Config additions to `PollingConfig`:
- `cadence_fast_s: float = 0.5`
- `cadence_slow_s: float = 5.0`
- `cadence_audit_s: float = 30.0`
- `idle_transition_s: float = 10.0`

Because these are new YAML-visible keys under the existing `polling:` section, the same
change must update `config.sample.yml`, the config wizard surface/guidance, and
`docs/project/spec/teleclaude-config.md`.

**Why:** Fixed 1.0s cadence treats idle and active sessions identically. With 27+
sessions, this means ~27 tmux subprocesses per second even when most sessions are idle.
Adaptive cadence lets active sessions poll at 0.5s while idle sessions back off to 5s,
reducing steady-state tmux churn by ~5x for idle sessions. The audit path ensures drift
recovery even if the wake signal misses events.

**Verification:**
- [ ] `CadenceState` exists with fast/slow/audit modes
- [ ] Active sessions poll at `cadence_fast_s`
- [ ] Idle sessions back off to `cadence_slow_s`
- [ ] Audit snapshots fire every `cadence_audit_s`
- [ ] Transition slow → fast on wake signal or user input
- [ ] Config knobs tunable via `config.polling`
- [ ] Test: cadence transitions work correctly in isolation
- [ ] `config.sample.yml`, config wizard guidance/surface, and `teleclaude-config.md` all expose the new polling keys

**Referenced files:**
- `teleclaude/core/session_runtime.py` — add CadenceState + transition logic
- `teleclaude/core/output_poller.py` — use runtime cadence instead of fixed interval
- `teleclaude/config/__init__.py` — extend PollingConfig
- `config.sample.yml` — document the new polling keys
- `docs/project/spec/teleclaude-config.md` — keep config spec in sync with polling surface
- `teleclaude/cli/config_handlers.py` — confirm wizard-visible polling section wiring
- `teleclaude/cli/tui/config_components/guidance.py` — add operator guidance for new polling fields
- `tests/unit/test_session_runtime.py` — add cadence transition tests
- `tests/unit/test_config_wizard_guidance.py` — verify wizard exposure stays in sync

### Task 4.3: Make rendered snapshots conditional

**What:** In the poll loop, skip `capture-pane` when the session is idle, not dirty,
and not due for an audit snapshot. Capture immediately on wake, turn activity, startup,
or reconnect.

**Why:** This combines wake signals (4.1) and adaptive cadence (4.2) into the actual
capture-skip logic. Without conditional capture, the runtime still calls `capture-pane`
on every tick even with slower cadence. With conditional capture, idle sessions only
invoke tmux for audit snapshots (~1 call per 30s), while active sessions capture on
every wake signal.

**Verification:**
- [ ] Idle sessions skip `capture-pane` between audit intervals
- [ ] Wake-dirty sessions capture immediately
- [ ] Startup/reconnect triggers immediate capture
- [ ] Codex semantic events still emit correctly on active sessions
- [ ] Test: idle session → capture count << poll iteration count

**Referenced files:**
- `teleclaude/core/output_poller.py` — add capture-skip logic
- `teleclaude/core/session_runtime.py` — expose `should_capture()` query

---

## Phase 5: Ephemeral Control Lane

### Task 5.1: Introduce per-session control queue

**What:** Create `teleclaude/core/session_control_queue.py` with:

`SessionControlQueue` — per-session `asyncio.Queue` for compound control actions:
- `enqueue(action: ControlAction) -> ControlReceipt` — returns immediately
- Internal worker: drains queue sequentially, handles tmux timing
- Lifecycle: created with runtime, drained on cleanup, NOT persisted

`ControlAction` — `action_type: str`, `payload: dict`, `session_id: str`
`ControlReceipt` — `status: str` ("queued"|"dispatched"|"failed"), `action_id: str`

**Why:** The 1.0s delay in `tmux_bridge._send_keys_tmux()` (line 709) blocks the
calling coroutine inline. For durable user messages this is already absorbed by the
inbound queue, but compound control paths (escape with args at
`command_handlers.py:1265-1320`) still block their callers. The queue decouples callers
from tmux timing. The requirements scope this to internal delayed text-injection paths,
not the public key-only API.

**Verification:**
- [ ] `SessionControlQueue` exists with enqueue/worker/cleanup lifecycle
- [ ] Enqueue returns `ControlReceipt` immediately
- [ ] Worker processes items sequentially with tmux timing
- [ ] Queue is ephemeral: not persisted, drained on cleanup
- [ ] Direct single-key controls remain direct — NOT queued

**Referenced files:**
- `teleclaude/core/session_control_queue.py` — create
- `teleclaude/core/session_runtime.py` — add `control_queue` field
- `tests/unit/test_session_control_queue.py` — create

### Task 5.2: Route compound controls through queue

**What:** Modify `escape_command` handler's compound path (with args,
`command_handlers.py:1265-1320`) to enqueue through `SessionControlQueue` instead of
blocking inline. The handler returns immediately; the queue worker executes:
1. `send_escape()` — immediate
2. `sleep(0.1)` — controlled by worker
3. `process_text(text, send_enter=True)` — with its 1.0s bridge sleep

Plain escape (no args) remains direct at line 1322-1344.
All single-key controls remain direct.
Public `/sessions/{id}/keys` API unchanged.
Durable `/message` delivery via inbound queue unchanged.

**Why:** Only compound paths with inline delays benefit from queueing. Simple keys are
latency-sensitive and gain nothing from queue overhead. The requirements explicitly
exclude expanding the key-only API and reworking single-key controls.

**Verification:**
- [ ] Compound escape+text enqueues instead of blocking
- [ ] Plain escape (no args) remains direct
- [ ] Simple key controls do NOT go through queue
- [ ] Public `/sessions/{id}/keys` API behavior unchanged
- [ ] Durable `/message` delivery unchanged

**Referenced files:**
- `teleclaude/core/command_handlers.py` — update escape_command compound path
- `teleclaude/core/session_control_queue.py` — queue executes via `_send_keys_tmux()`

---

## Phase 6: Validation and Documentation

### Task 6.1: Performance instrumentation

**What:** Add counters to `SessionRuntime`: `capture_count`, `wake_count`,
`skip_count`, `idle_transition_count`, and `tmux_subprocess_count` for every
runtime-owned tmux probe (`capture-pane`, liveness/pane-dead checks, directory checks,
and pipe attach/detach). Emit summary metrics at existing
`OUTPUT_METRICS_SUMMARY_INTERVAL_S` boundary alongside output cadence metrics, with
matched idle-window labels so before/after runs can be compared directly.

**Why:** Success criteria require demonstrable before/after reduction in tmux subprocess
churn for idle sessions.

**Verification:**
- [ ] Runtime counters exist and increment correctly
- [ ] Metrics logged at summary intervals with both capture frequency and tmux subprocess counts
- [ ] Before/after comparison over matched idle windows shows lower tmux subprocess counts and lower capture frequency while audit snapshots remain visible

**Referenced files:**
- `teleclaude/core/session_runtime.py` — add counters
- `teleclaude/core/output_poller.py` — increment runtime-owned tmux probe counters
- `teleclaude/core/polling_coordinator.py` — emit in existing metrics path

### Task 6.2: Test realignment

**What:** Update tests that overfit the old hot-loop probe order to assert behavioral
contracts instead.

- `test_output_poller.py`: remove assertions that `session_exists()` runs before every
  capture. Replace with: capture success implies alive, capture failure triggers check.
- `test_polling_coordinator.py`: update imports for items in `codex_render_semantics.py`.
  Update state access to use `SessionRuntime` via registry.
- `test_codex_replay.py`: verify pass against extracted module.
- `test_command_handlers.py`: preserve `get_session_data` transcript/tmux fallback and
  headless adoption semantics while the runtime adds reconciliation snapshots.

**Why:** Tests locking in implementation details become maintenance liabilities during
refactors. Requirements explicitly call this out.

**Verification:**
- [ ] No test asserts `session_exists()` per-tick
- [ ] Tests assert behavioral contracts: output detection, death detection, event emission
- [ ] All semantic invariant tests pass
- [ ] Replay corpus tests pass against extracted module
- [ ] Docs/tests explicitly cover startup, reconnect, headless-bootstrap, and drift-recovery lane authority

**Referenced files:**
- `tests/unit/test_output_poller.py` — update health check assertions
- `tests/unit/test_polling_coordinator.py` — update imports + state access
- `tests/unit/test_codex_replay.py` — verify extracted module imports
- `tests/unit/test_command_handlers.py` — preserve fallback + headless adoption contracts

### Task 6.3: Documentation update

**What:** Rewrite `docs/project/design/architecture/output-polling.md` to describe:
- Three-lane observability model (hook, render, transcript)
- `SessionRuntime` actor and `SessionRuntimeRegistry`
- Wake-driven capture via `pipe-pane`
- Adaptive cadence states and transitions
- Ephemeral control queue for compound actions
- Lane-authority table for startup, reconnect, headless-bootstrap, and drift-recovery
- Updated Mermaid sequence diagrams
- Preserve adapter-level QoS section (unchanged)

Update `docs/project/design/architecture/tmux-management.md`:
- `pipe-pane` wake signal contract
- Headless adoption/bootstrap reconciliation requirements
- Per-session tmp cleanup in teardown

**Why:** Current docs describe a simpler diff/cursor model and omit the Codex render
lane. Stale docs mislead future work. Requirements explicitly include this.

**Verification:**
- [ ] Docs describe three-lane model, not single diff loop
- [ ] Docs describe adaptive cadence and wake signals
- [ ] Docs make startup/reconnect/headless-bootstrap/drift-recovery lane authority explicit
- [ ] No stale references to old hot-loop probe order
- [ ] Mermaid diagrams match implemented behavior

**Referenced files:**
- `docs/project/design/architecture/output-polling.md` — rewrite
- `docs/project/design/architecture/tmux-management.md` — update

### Task 6.4: Integration and smoke verification

**What:** Full suite run, daemon restart safety, and regression checks.

**Verification:**
- [ ] `make test` passes
- [ ] `make lint` passes
- [ ] Daemon restart does not break session continuity
- [ ] `get_session_data` transcript/tmux fallback works
- [ ] Durable queued user-message delivery unchanged
- [ ] `telec todo demo validate codex-render-semantic-runtime` exits 0

**Referenced files:**
- All modified files (full regression surface)

---

## Task Dependency Graph

```
Phase 1 (parallel):
  Task 1.1 (capture budget)
  Task 1.2 (teardown tmp)
  Task 1.3 (cheapen hot loop)

Phase 2 (after Phase 1):
  Task 2.1 (fixture corpus)
  Task 2.2 (replay tests) ← depends on 2.1

Phase 3 (after Phase 2):
  Task 3.1 (extract Codex semantics) ← depends on 2.2 (safety net exists)
  Task 3.2 (SessionRuntime actor) ← depends on 3.1

Phase 4 (after Phase 3):
  Task 4.1 (pipe-pane wake) ← depends on 3.2
  Task 4.2 (adaptive cadence) ← depends on 3.2
  Task 4.3 (conditional capture) ← depends on 4.1 + 4.2

Phase 5 (parallel with Phase 4):
  Task 5.1 (control queue) ← depends on 3.2 (for runtime field)
  Task 5.2 (route compound controls) ← depends on 5.1

Phase 6 (after Phases 4 + 5):
  Task 6.1 (instrumentation) ← depends on 4.3
  Task 6.2 (test realignment) ← depends on 3.1 + 4.3
  Task 6.3 (doc update) ← depends on 4.3 + 5.2
  Task 6.4 (integration smoke) ← depends on all
```

---

## Referenced Paths (all files)

### New files
- `teleclaude/core/codex_render_semantics.py`
- `teleclaude/core/session_runtime.py`
- `teleclaude/core/session_control_queue.py`
- `tests/unit/test_codex_replay.py`
- `tests/unit/test_session_runtime.py`
- `tests/unit/test_session_control_queue.py`
- `tests/fixtures/codex_pane_snapshots/` (directory + fixture files)

### Modified files
- `config.sample.yml`
- `teleclaude/constants.py`
- `teleclaude/config/__init__.py`
- `teleclaude/cli/config_handlers.py`
- `teleclaude/cli/tui/config_components/guidance.py`
- `teleclaude/core/tmux_bridge.py`
- `teleclaude/core/tmux_io.py`
- `teleclaude/core/output_poller.py`
- `teleclaude/core/polling_coordinator.py`
- `teleclaude/core/session_cleanup.py`
- `teleclaude/core/command_handlers.py`
- `teleclaude/daemon.py`
- `tests/unit/test_command_handlers.py`
- `tests/unit/test_config_wizard_guidance.py`
- `tests/unit/test_output_poller.py`
- `tests/unit/test_polling_coordinator.py`
- `docs/project/design/architecture/output-polling.md`
- `docs/project/design/architecture/tmux-management.md`
- `docs/project/spec/teleclaude-config.md`

### Unchanged (dependency verification only)
- `teleclaude/api_server.py`
- `teleclaude/cli/api_client.py`
- `teleclaude/core/agent_coordinator.py`
- `teleclaude/output_projection/terminal_live_projector.py`

---

## Deferred / Not Planned

- **Real pane snapshot corpus**: Task 2.1 fixtures are synthetic. Capturing real
  snapshots from live sessions requires instrumentation not yet built.
- **Cross-process QoS rate enforcement**: Out of scope per requirements.
- **Expanding public `/sessions/{id}/keys` API**: Explicitly out of scope.
- **Daemon wiring refactor**: The daemon's `_start_polling_for_session` /
  `_poll_and_send_output` wrappers remain as-is. The runtime is integrated through
  the polling coordinator, not by replacing the daemon's bootstrap path. This limits
  blast radius. A future todo can consolidate daemon polling wiring.
