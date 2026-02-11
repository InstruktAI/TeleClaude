# Implementation Plan: runtime-settings-tts-toggle

## Overview

Four-phase approach: clean up dead config code, build the runtime settings layer with persistence, expose it via API, then wire into the TUI footer. Each phase is independently testable.

## Phase 1: SummarizerConfig Removal

### Task 1.1: Remove SummarizerConfig from config module

**File(s):** `teleclaude/config/__init__.py`

- [x] Delete `SummarizerConfig` dataclass (lines 228-239)
- [x] Remove `summarizer` field from `Config` dataclass (line 287)
- [x] Remove `"summarizer"` block from `DEFAULT_CONFIG` (lines 380-383)
- [x] Remove `summarizer_raw` variable and `SummarizerConfig(...)` construction from `_build_config` (lines 559, 643-647)

### Task 1.2: Decouple summarizer and feedback from config

**File(s):** `teleclaude/core/summarizer.py`, `teleclaude/core/feedback.py`

- [x] `summarizer.py` line 69: replace `config.summarizer.max_summary_words` with `30`; remove `from teleclaude.config import config`
- [x] `feedback.py`: simplify `get_last_feedback()` to always return `session.last_feedback_summary or session.last_feedback_received`; remove config import

### Task 1.3: Clean up test fixtures

**File(s):** `tests/integration/conftest.py`

- [x] Remove `MockSummarizer` and `max_summary_words` references

---

## Phase 2: RuntimeSettings + Persistence

### Task 2.1: Add ruamel.yaml dependency

**File(s):** `pyproject.toml`

- [x] Add `"ruamel.yaml>=0.18.0"` to `[project.dependencies]`

### Task 2.2: Create RuntimeSettings class

**File(s):** `teleclaude/config/runtime_settings.py` (new)

- [x] `RuntimeSettings.__init__(config_path, tts_manager)` — seed `tts_enabled` from `config.tts.enabled`
- [x] `MUTABLE_SETTINGS` whitelist: `{"tts.enabled"}`
- [x] `patch(updates: dict) -> dict` — validate keys, mutate in-memory, update `tts_manager.enabled`, schedule debounced write
- [x] `get_state() -> dict` — return `{"tts": {"enabled": self.tts_enabled}}`
- [x] `_schedule_flush()` — cancel previous debounce task, create new one with 500ms delay
- [x] `_flush_to_disk()` — use `ruamel.yaml` to load config, deep-merge pending patches, write back

### Task 2.3: Wire RuntimeSettings into daemon

**File(s):** `teleclaude/daemon.py`, `teleclaude/core/lifecycle.py`

- [x] Create `RuntimeSettings(config_path, tts_manager)` on daemon after `TTSManager` init
- [x] Store as `self.runtime_settings` on daemon
- [x] Pass `runtime_settings` to `DaemonLifecycle` → `APIServer`

---

## Phase 3: API Endpoints

### Task 3.1: Add settings endpoints to APIServer

**File(s):** `teleclaude/api_server.py`

- [x] Accept `runtime_settings` in `APIServer.__init__`
- [x] `GET /settings` — return `runtime_settings.get_state()`
- [x] `PATCH /settings` — parse JSON body, call `runtime_settings.patch()`, return result; 400 on invalid keys

### Task 3.2: Add settings methods to TUI API client

**File(s):** `teleclaude/cli/api_client.py`

- [x] `get_settings() -> dict` — `GET /settings`
- [x] `patch_settings(updates: dict) -> dict` — `PATCH /settings`

---

## Phase 4: TUI Footer Toggle

### Task 4.1: Extend Footer widget

**File(s):** `teleclaude/cli/tui/widgets/footer.py`

- [x] Accept `tts_enabled: bool` in constructor
- [x] Render `[TTS]` indicator to the right of agent pills (bright when on, dim when off)
- [x] Track column range of TTS indicator for click hit detection
- [x] Expose `handle_click(col: int) -> bool` — returns True if click was on TTS region

### Task 4.2: Wire TTS state into TUI app

**File(s):** `teleclaude/cli/tui/app.py`

- [x] Add `self.tts_enabled: bool = False` to app state
- [x] In `_refresh_data()`, call `api.get_settings()` and update `self.tts_enabled`
- [x] Pass `tts_enabled` to `Footer` constructor
- [x] In `KEY_MOUSE` / `BUTTON1_CLICKED` handler: check if click on footer row (`height - 1`); delegate to `footer.handle_click(mx)`
- [x] If TTS toggle hit, schedule `api.patch_settings({"tts": {"enabled": not self.tts_enabled}})` async call
- [x] Optional: map hotkey `v` to toggle TTS

---

## Phase 5: Validation

### Task 5.1: Tests

- [x] Unit test `RuntimeSettings.patch()` — valid keys, invalid keys, in-memory mutation
- [x] Unit test debounced flush — verify single write after rapid patches
- [x] Unit test `GET /settings` and `PATCH /settings` API responses
- [x] Verify existing test suite passes (`make test`) — 1269 passed, 1 pre-existing failure unrelated

### Task 5.2: Quality Checks

- [x] Run `make lint` — all checks passed (ruff format, ruff check, pyright 0 errors)
- [x] Validate toggle persistence path via automated tests (`tests/unit/test_runtime_settings.py`) — runtime mutation and comment-preserving YAML flush verified
- [x] Validate API contract via automated endpoint tests (`tests/unit/test_runtime_settings.py`) — valid patch succeeds; unknown top-level/nested keys return `400`

---

## Phase 6: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable) — no deferrals
