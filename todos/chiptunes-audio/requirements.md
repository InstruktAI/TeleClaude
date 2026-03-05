# Requirements: chiptunes-audio

## Goal

Add background ChipTunes music playback using C64 SID files from the HVSC collection
(`assets/audio/C64Music/`). The feature is a runtime toggle — like TTS — with its own
icon in the TUI footer, keybinding, and config persistence.

## Scope

### In scope

- **SID playback engine**: Three-layer pure-Python pipeline:
  1. **SID header parser** — parse PSID/RSID headers to extract load/init/play addresses,
     speed flags, subtune count.
  2. **6502 CPU emulator** (`py65emu`, on PyPI) — load SID payload into 64KB address space,
     run `initAddress` then `playAddress` at frame rate (50Hz PAL / 60Hz NTSC), intercept
     writes to SID registers at `$D400–$D418`.
  3. **SID chip emulator** (`pyresidfp`, on PyPI) — forward intercepted register writes,
     clock per frame, produce PCM samples.
  Audio output via `sounddevice.RawOutputStream` (non-blocking callback, `int16` buffers).
- **ChiptunesManager**: Singleton manager (analogous to `TTSManager`) that owns playback
  state, random track selection from the HVSC tree, and start/stop lifecycle.
- **Runtime settings integration**: New `chiptunes` section in `RuntimeSettings` with
  `enabled: bool`, persisted to `config.yml` alongside `tts`.
- **API endpoint**: Extend `PATCH /settings` to accept `chiptunes.enabled` patches.
- **TUI footer icon**: Reassign the speaker icon (🔊) to ChipTunes. Give TTS a new
  speech-bubble or talking-face icon (🗣️ or 💬).
- **TUI keybinding**: New key for ChipTunes toggle. Candidate: `m` (music). The existing
  `v` (voice) stays on TTS.
- **Click toggle**: Footer icon click toggles chiptunes on/off (same pattern as TTS click).
- **Track rotation**: On enable, pick a random `.sid` file from the HVSC tree and start
  playback. When a track ends, auto-advance to another random track. On disable, stop
  playback immediately.
- **Coexistence with TTS**: ChipTunes and TTS can both be enabled. When TTS speaks,
  ChipTunes audio should duck (reduce volume) or pause briefly, then resume. If ducking
  is too complex for v1, pause-and-resume is acceptable.
- **Config section**: `chiptunes` key in `config.yml` with `enabled`, `music_dir`
  (default: `assets/audio/C64Music`), and optional `volume` (0.0–1.0, default 0.5).

### Out of scope

- Track browsing / selection UI (just random shuffle for now).
- Playlist management or favorites.
- Visualizer / waveform display.
- Support for non-SID chiptune formats (NSF, VGM, etc.).
- Remote playback (chiptunes only play on the local terminal).

## Success Criteria

- [ ] Pressing `m` in the TUI toggles chiptunes playback on/off.
- [ ] Footer shows a distinct icon for chiptunes (speaker) and TTS (speech icon),
      each reflecting their enabled/disabled state.
- [ ] Enabling chiptunes plays a random `.sid` file from the HVSC collection audibly.
- [ ] Disabling chiptunes stops audio immediately.
- [ ] When a track finishes, the next random track starts automatically.
- [ ] The `chiptunes.enabled` setting persists across TUI restarts via `config.yml`.
- [ ] `PATCH /settings {"chiptunes": {"enabled": true}}` works via the API.
- [ ] TTS and chiptunes can coexist without crashes (TTS pauses or ducks chiptunes).
- [ ] No audio playback occurs when the TUI is not the active terminal origin
      (same guard as TTS: check `InputOrigin.TERMINAL`).

## Constraints

- Audio playback must be non-blocking (background thread) so the TUI event loop is
  never stalled. The `sounddevice` callback runs in a C thread; the 6502 emulator runs
  in a Python thread that pre-fills a buffer.
- The HVSC collection is large (60K+ files). Track discovery must be lazy or cached —
  do not scan the full tree on startup.
- macOS is the primary platform. `sounddevice` requires PortAudio (`brew install portaudio`
  or bundled).
- `py65emu` is pure Python and may be slow. The player must pre-buffer several seconds
  of audio ahead of playback to absorb CPU jitter. If real-time emulation proves
  impossible, the fallback is `sidplayfp` CLI (Homebrew `libsidplayfp`) writing to a
  temp WAV file.
- RSID-format tunes (with `playAddress == 0`) are interrupt-driven and significantly
  harder to emulate. These should be skipped in v1 (PSID tunes only).
- Dependencies: `pyresidfp>=0.17.0`, `py65emu>=0.1.0`, `sounddevice>=0.5.5`.

## Risks

- `py65emu` performance: pure-Python 6502 emulation may not sustain real-time for
  complex tunes. Mitigation: pre-buffer audio ahead; if still insufficient, fall back
  to `sidplayfp` CLI subprocess writing WAV.
- Some tunes rely on C64 Kernal ROM routines (`$E000–$FFFF`). Without ROM images,
  these tunes will crash/go silent. Mitigation: skip and advance to next track on
  error; optionally load ROM images if available.
- CIA timer tunes (speed flag bit = 1) use custom playback rates. v1 supports VBI
  tunes only (50/60Hz); CIA support is deferred.
- Audio ducking/coexistence with TTS may introduce timing complexity. Acceptable v1:
  pause chiptunes during TTS, resume after.
- Some `.sid` files may be malformed or multi-song (subtunes). The player should handle
  errors gracefully and skip to the next track.
