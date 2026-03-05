# Implementation Plan: chiptunes-audio

## Overview

Add a ChipTunes SID playback feature mirroring the TTS toggle pattern: a manager module,
runtime settings integration, API patch support, and TUI footer icon with keybinding.

The SID playback uses a three-layer pure-Python pipeline:
1. **SID parser** — reads PSID/RSID headers from `.sid` files
2. **6502 CPU** (`py65emu`) — executes the embedded machine code, intercepts SID register writes
3. **SID chip** (`pyresidfp`) — emulates the SID sound chip, produces PCM samples

Audio output via `sounddevice.RawOutputStream` (non-blocking, `int16` buffers).

## Phase 1: Core Playback Engine

### Task 1.1: SID file parser

**File(s):** `teleclaude/chiptunes/sid_parser.py`

- [ ] Create `SIDHeader` dataclass with fields:
  `magic`, `version`, `data_offset`, `load_address`, `init_address`, `play_address`,
  `songs`, `start_song`, `speed`, `name`, `author`, `released`, `flags`, `payload`
- [ ] Parse PSID v1–v4 and RSID headers (big-endian, fixed offsets per spec)
- [ ] Handle `load_address == 0` case (first 2 bytes of payload are the real address, LE)
- [ ] Extract speed flags (bit per subtune: 0=VBI 50/60Hz, 1=CIA timer)
- [ ] Extract PAL/NTSC flag from v2+ `flags` field (bit 2-3: 0=unknown, 1=PAL, 2=NTSC)
- [ ] Reject RSID files with `play_address == 0` (interrupt-driven, unsupported in v1)

### Task 1.2: 6502 CPU driver with SID register interception

**File(s):** `teleclaude/chiptunes/sid_cpu.py`

- [ ] Create `SIDInterceptMMU` subclass of `py65emu.mmu.MMU`:
  - Override `cpu_write(addr, value)` to capture writes to `$D400–$D418`
    (NB: PyPI `py65emu==0.1.0` (TXC fork) uses `cpu_write`/`cpu_read`, NOT `write`/`read`)
  - Store captured writes as `list[tuple[int, int]]` (register offset, value)
  - Provide `flush_writes() -> list[tuple[int, int]]` to drain the buffer
- [ ] Create `SIDDriver` class:
  - `__init__(header: SIDHeader)` — set up 64KB address space, load payload at `load_address`
  - `init_tune(subtune: int = 0)` — place JSR stub + BRK at driver address,
    set A register to subtune number, execute until return
  - `play_frame() -> list[tuple[int, int]]` — JSR to `play_address`, execute
    until return, return captured SID register writes
  - RTS detection: push sentinel return address before JSR, detect when PC
    returns to sentinel
  - Cycle budget guard: abort frame if > 100K cycles (runaway tune protection)

### Task 1.3: SID chip renderer

**File(s):** `teleclaude/chiptunes/sid_renderer.py`

- [ ] Create `SIDRenderer` class wrapping `pyresidfp.SoundInterfaceDevice`:
  - `__init__(sample_rate: int = 48000, chip_model: str = "MOS6581", pal: bool = True)`
  - Configure clock frequency (PAL: 985248 Hz, NTSC: 1022730 Hz)
    Use `SoundInterfaceDevice.PAL_CLOCK_FREQUENCY` / `.NTSC_CLOCK_FREQUENCY` constants
  - `render_frame(writes: list[tuple[int, int]], frame_duration_s: float) -> bytes`
    — apply register writes, clock the SID, return `int16` PCM bytes
  - Handle sample format: `SoundInterfaceDevice.clock(timedelta)` returns `list[int]`
    of signed 16-bit values (-32768..32767). Pack to `int16` bytes via `struct` or
    `array.array('h', samples).tobytes()`. Use raw `SID.clock(cycles)` for precise
    cycle-level control if needed.
  - Apply volume scaling (0.0–1.0)

### Task 1.4: Streaming player

**File(s):** `teleclaude/chiptunes/player.py`

- [ ] Create `ChiptunesPlayer` class:
  - `__init__(volume: float = 0.5)`
  - `play(sid_path: Path) -> None`:
    1. Parse SID header
    2. Create `SIDDriver` and `SIDRenderer`
    3. Init tune (default subtune)
    4. Start background thread that runs the frame loop:
       - Call `driver.play_frame()` at frame rate (50/60 Hz)
       - Pass register writes to `renderer.render_frame()`
       - Feed PCM bytes to a `queue.Queue` (thread-safe buffer)
    5. Open `sounddevice.RawOutputStream` with callback that pulls from the queue
  - `stop() -> None` — signal stop via `threading.Event`, close stream
  - `pause() -> None` / `resume() -> None` — pause/resume the sounddevice stream
  - `is_playing: bool` property
  - `on_track_end: Callable | None` — callback when track ends or errors
- [ ] Pre-buffer: generate 2–3 seconds of audio before starting the stream
- [ ] Error handling: on decode error, log warning, signal track-end (skip to next)
- [ ] Graceful cleanup: ensure stream and thread are always cleaned up

### Task 1.5: Manager

**File(s):** `teleclaude/chiptunes/manager.py`, `teleclaude/chiptunes/__init__.py`

- [ ] Create `ChiptunesManager` class:
  - `__init__(music_dir: Path, volume: float = 0.5)`
  - `enabled: bool` property
  - `start() -> None` — pick random PSID track, start playback, register
    `on_track_end` callback for auto-advance
  - `stop() -> None` — stop playback
  - `pause() -> None` / `resume() -> None` — delegate to player
  - `_pick_random_track() -> Path` — lazy discovery: on first call, walk
    `music_dir` tree and cache all `.sid` paths. Use `random.choice()`.
    Filter: skip RSID files (read first 4 bytes: `b'RSID'`).
  - `_on_track_end() -> None` — auto-advance to next random track
- [ ] Lazy track list: cache after first walk. 60K+ paths is ~few MB in memory.
  No startup cost if chiptunes is disabled.

### Task 1.6: Dependencies

**File(s):** `pyproject.toml`

- [ ] Add optional dependencies group `[chiptunes]`:
  `pyresidfp>=0.17.0`, `py65emu>=0.1.0`, `sounddevice>=0.5.5`
- [ ] Document PortAudio system dependency: `brew install portaudio`
- [ ] Import guards in `teleclaude/chiptunes/` for graceful degradation
  when deps are not installed

---

## Phase 2: Runtime Settings & API

### Task 2.1: Extend RuntimeSettings

**File(s):** `teleclaude/config/runtime_settings.py`

- [ ] Add `ChiptunesSettings` dataclass: `enabled: bool = False`
- [ ] Add `chiptunes` field to `SettingsState`
- [ ] Add `ChiptunesSettingsPatch` and include in `SettingsPatch`
- [ ] Extend `RuntimeSettings.__init__` to accept `ChiptunesManager`
- [ ] Extend `RuntimeSettings.patch()` to handle `chiptunes.enabled` updates
  (start/stop manager on toggle)
- [ ] Extend `RuntimeSettings.parse_patch()` to validate `chiptunes` key
- [ ] Extend `_flush_to_disk()` to persist `chiptunes.enabled`

### Task 2.2: Extend config model

**File(s):** `teleclaude/config/__init__.py`

- [ ] Add `ChiptunesConfig` dataclass: `enabled: bool`, `music_dir: str | None`,
  `volume: float = 0.5`
- [ ] Add `chiptunes: ChiptunesConfig | None` to main config

### Task 2.3: Extend API

**File(s):** `teleclaude/api_models.py`, `teleclaude/api_server.py`

- [ ] Add `ChiptunesSettingsPatchDTO` to api_models
- [ ] Extend `SettingsPatchDTO` with `chiptunes` field
- [ ] Extend `SettingsDTO` response with `chiptunes` state
- [ ] Extend API client model (`teleclaude/cli/models.py`) with chiptunes patch info

---

## Phase 3: TUI Integration

### Task 3.1: Add chiptunes toggle to footer

**File(s):** `teleclaude/cli/tui/widgets/telec_footer.py`,
`teleclaude/cli/tui/widgets/status_bar.py`

- [ ] Add `chiptunes_enabled = reactive(False)` property
- [ ] Change TTS icon from 🔊/🔇 to 🗣️ (speaking head) for enabled, dim for disabled
- [ ] Add chiptunes icon: 🔊 (speaker) for enabled, 🔇 for disabled — positioned
  between TTS and animation icons
- [ ] Track click region for chiptunes icon
- [ ] Post `SettingsChanged("chiptunes_enabled", ...)` on click
- [ ] Add `watch_chiptunes_enabled` watcher for refresh

### Task 3.2: Add keybinding and app handler

**File(s):** `teleclaude/cli/tui/app.py`

- [ ] Add binding: `Binding("m", "toggle_chiptunes", "Music", key_display="m")`
- [ ] Add `action_toggle_chiptunes()` → `_toggle_chiptunes()` (async worker,
  same pattern as `_toggle_tts`)
- [ ] Handle `SettingsChanged("chiptunes_enabled", ...)` in `on_settings_changed`
- [ ] Include `chiptunes_enabled` in `DataRefreshed` message and refresh handler

### Task 3.3: Update DataRefreshed message

**File(s):** `teleclaude/cli/tui/messages.py`

- [ ] Add `chiptunes_enabled: bool` to `DataRefreshed` constructor

---

## Phase 4: TTS Coexistence

### Task 4.1: Pause/resume chiptunes during TTS

**File(s):** `teleclaude/tts/manager.py`, `teleclaude/chiptunes/manager.py`

- [ ] Before TTS `trigger_event` / `speak` queues audio, call
  `chiptunes_manager.pause()` if chiptunes is playing
- [ ] After TTS playback completes (in `_handle_tts_result` callback), call
  `chiptunes_manager.resume()`
- [ ] Inject `ChiptunesManager` reference into `TTSManager` (or use a shared
  audio coordinator)

---

## Phase 5: Validation

### Task 5.1: Tests

- [ ] Unit test: `SIDHeader` parser with a known `.sid` file from HVSC
- [ ] Unit test: `SIDInterceptMMU` captures writes to `$D400–$D418`
- [ ] Unit test: `SIDDriver` init + play_frame returns register writes
- [ ] Unit test: `SIDRenderer` produces non-zero PCM bytes from register writes
- [ ] Unit test: `ChiptunesPlayer` start/stop lifecycle
- [ ] Unit test: `ChiptunesManager` start/stop/pause/resume lifecycle
- [ ] Unit test: RuntimeSettings patch for `chiptunes.enabled`
- [ ] Unit test: API patch validation for `chiptunes` key
- [ ] Integration test: TTS + chiptunes coexistence (pause/resume)
- [ ] Run `make test`

### Task 5.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 6: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
