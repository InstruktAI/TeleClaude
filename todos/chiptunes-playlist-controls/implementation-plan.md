# Implementation Plan: chiptunes-playlist-controls

## Overview

Four-layer change: worker gets track history and prev/next commands, manager gets proxy methods, daemon broadcasts enriched track events, TUI footer replaces the single toggle with a player control group + favorites persistence.

## Phase 1: Worker Track History & Navigation

### Task 1.1: Add track history to worker

**File(s):** `teleclaude/chiptunes/worker.py`

- [x] Add `_history: list[Path]` and `_history_index: int` to `_Worker.__init__`
- [x] Refactor `_play_random()` into `_play_track(track: Path)` that handles stop-current, emit, play
- [x] New `_play_next()`: if `_history_index < len(_history) - 1`, advance index and replay; else pick new random, append to history, set index to end
- [x] New `_play_prev()`: if `_history_index > 0`, decrement index and replay from history; else no-op
- [x] Update `_on_track_end()` to call `_play_next()` instead of `_play_random()`
- [x] `_play_random()` still used for initial start — calls `_play_next()` which picks random at end of history

### Task 1.2: Add next/prev commands to worker protocol

**File(s):** `teleclaude/chiptunes/worker.py`

- [x] Handle `{"cmd": "next"}` → calls `_play_next()`
- [x] Handle `{"cmd": "prev"}` → calls `_play_prev()`

### Task 1.3: Enrich track_start event with SID path

**File(s):** `teleclaude/chiptunes/worker.py`

- [x] `_emit("track_start", track=track_label, sid_path=str(track))` — add the SID file path so the TUI can match it against favorites

## Phase 2: Manager & Daemon Wiring

### Task 2.1: Add next/prev to manager

**File(s):** `teleclaude/chiptunes/manager.py`

- [x] `def next_track(self) -> None:` sends `{"cmd": "next"}`
- [x] `def prev_track(self) -> None:` sends `{"cmd": "prev"}`

### Task 2.2: Enrich ChiptunesTrackEvent DTO

**File(s):** `teleclaude/api_models.py`

- [x] Add `sid_path: str` field to `ChiptunesTrackEventDTO`

### Task 2.3: Pass sid_path through daemon broadcast

**File(s):** `teleclaude/daemon.py`

- [x] Update `on_track_start` callback signature to receive both `track_label` and `sid_path`
- [x] Update `_on_chiptunes_track_start` to include `sid_path` in the broadcast payload
- [x] Update manager's `_handle_event` to extract and forward `sid_path` from the worker event

## Phase 3: Favorites Persistence

### Task 3.1: Favorites file read/write utility

**File(s):** `teleclaude/chiptunes/favorites.py` (new)

- [x] `FAVORITES_PATH = Path("~/.teleclaude/chiptunes-favorites.json").expanduser()`
- [x] `def load_favorites() -> list[dict]` — read JSON file, return list (empty list if missing/malformed)
- [x] `def save_favorite(track_name: str, sid_path: str) -> None` — append entry with `track_name`, `sid_path`, `saved_at` ISO timestamp; deduplicate by `sid_path`
- [x] `def is_favorited(sid_path: str) -> bool` — check if sid_path exists in favorites

## Phase 4: TUI Footer Player Controls

### Task 4.1: Add reactive state for player controls

**File(s):** `teleclaude/cli/tui/widgets/telec_footer.py`

- [x] Add reactives: `chiptunes_playing = reactive(False)`, `chiptunes_track = reactive("")`, `chiptunes_sid_path = reactive("")`, `chiptunes_favorited = reactive(False)`
- [x] Add watchers that call `self.refresh()` on change

### Task 4.2: Render player control group

**File(s):** `teleclaude/cli/tui/widgets/telec_footer.py`

- [x] Replace the single chiptunes icon block with four icons: `⏮` `⏯`/`⏸` `⏭` `⭐`/`✅`
- [x] ⏯️ shows `⏸` when `chiptunes_playing` is True, `▶` when paused or disabled
- [x] ⭐ shows `✅` when `chiptunes_favorited` is True
- [x] All four icons dim when `chiptunes_enabled` is False
- [x] Track x-coordinate regions for each icon: `_prev_start_x`, `_play_start_x`, `_next_start_x`, `_fav_start_x` (and corresponding end positions)

### Task 4.3: Click handlers for player controls

**File(s):** `teleclaude/cli/tui/widgets/telec_footer.py`

- [x] Update `on_click` to detect which player icon was clicked based on x-coordinate regions
- [x] ⏮️ click → post `SettingsChanged("chiptunes_prev", None)`
- [x] ⏯️ click → post `SettingsChanged("chiptunes_play_pause", None)`
- [x] ⏭️ click → post `SettingsChanged("chiptunes_next", None)`
- [x] ⭐ click → post `SettingsChanged("chiptunes_favorite", None)`

### Task 4.4: App-level handlers for player control messages

**File(s):** `teleclaude/cli/tui/app.py`

- [x] Handle `chiptunes_play_pause`: if disabled → enable chiptunes (existing toggle); if playing → call pause API; if paused → call resume API
- [x] Handle `chiptunes_next`: call next-track API
- [x] Handle `chiptunes_prev`: call prev-track API
- [x] Handle `chiptunes_favorite`: call `save_favorite()` with current track info, update footer's `chiptunes_favorited` reactive
- [x] On `ChiptunesTrackEvent`: update footer's `chiptunes_track`, `chiptunes_sid_path`, `chiptunes_favorited` (check favorites file), set `chiptunes_playing = True`

### Task 4.5: API client methods for player controls

**File(s):** `teleclaude/cli/api_client.py`

- [x] Add `async def chiptunes_next(self)` → `POST /api/chiptunes/next`
- [x] Add `async def chiptunes_prev(self)` → `POST /api/chiptunes/prev`
- [x] Add `async def chiptunes_pause(self)` → `POST /api/chiptunes/pause`
- [x] Add `async def chiptunes_resume(self)` → `POST /api/chiptunes/resume`

### Task 4.6: Daemon API endpoints for next/prev

**File(s):** `teleclaude/api_server.py`

- [x] `POST /api/chiptunes/next` → calls `chiptunes_manager.next_track()`
- [x] `POST /api/chiptunes/prev` → calls `chiptunes_manager.prev_track()`
- [x] `POST /api/chiptunes/pause` → calls `chiptunes_manager.pause()`
- [x] `POST /api/chiptunes/resume` → calls `chiptunes_manager.resume()`

---

## Phase 5: Validation

### Task 5.1: Tests

- [x] Worker: test track history navigation (next appends, prev replays, boundary behavior)
- [x] Worker: test next/prev commands via protocol
- [x] Manager: test next_track/prev_track proxy methods
- [x] Favorites: test save, load, is_favorited, deduplication
- [x] DTO: test ChiptunesTrackEventDTO with sid_path field
- [x] Run `make test`

### Task 5.2: Quality Checks

- [x] Run `make lint`
- [x] Verify no unchecked implementation tasks remain

---

## Phase 6: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] SIGUSR2 reload and verify footer controls visually
