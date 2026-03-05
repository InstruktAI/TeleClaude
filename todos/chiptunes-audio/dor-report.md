# DOR Report: chiptunes-audio

## Gate Assessment

**Phase**: Gate (formal DOR validation — re-assessment)
**Assessed at**: 2026-03-05
**Previous verdict**: needs_work (score 5) — SID decoding approach unvalidated
**Current verdict**: pass (score 9)

## Gate Analysis

### 1. Intent & Success — PASS

Problem statement is clear: add background ChipTunes music playback using SID files
from the HVSC collection, toggled via TUI and API. Success criteria are concrete and
testable (keybinding, icon, audio, persistence, TTS coexistence). No changes since
previous assessment.

### 2. Scope & Size — PASS

Touches multiple layers but all follow proven patterns. Phase 1 (SID engine) now has
6 tasks instead of 3 — the increased granularity reflects the 3-layer pipeline
(parser, CPU driver, SID renderer, streaming player, manager, deps). The decomposition
is appropriate: each task has a clear boundary and testable output. Total: 14 tasks
across 6 phases. Fits a single focused session.

### 3. Verification — PASS

Unit tests updated to cover the new pipeline components: SID header parser, MMU
register interception, CPU driver init/play_frame, SID renderer PCM output, player
lifecycle, manager lifecycle, runtime settings patch, API validation. Integration test
for TTS coexistence. `make test` and `make lint` as gates.

### 4. Approach Known — PASS

**Previous blocker resolved.** The three-layer pipeline is now grounded in validated APIs:

**SID parser** — custom PSID/RSID header parser. The format is well-documented
(fixed binary layout, big-endian fields at known offsets). Straightforward implementation.

**6502 CPU** — `py65emu` (PyPI 0.1.0, TXC fork). API validated:
- `MMU` subclassable with `cpu_write(addr, value)` override for register interception
- `CPU(mmu, pc)` construction, `cpu.step()` execution, `cpu.r.a`/`.pc` register access
- `cpu.cc_total` cumulative cycle counter for budget guard
- BRK detection via flag check, RTS detection via opcode read before step
- Important: this is the TXC fork (PyPI), not docmarionum1 (GitHub-only). Method names
  are `cpu_write`/`cpu_read`, not `write`/`read`.

**SID chip** — `pyresidfp` (PyPI 0.17.0). API validated:
- `SoundInterfaceDevice(model, sampling_method, clock_frequency, sampling_frequency)`
- `SID.write(offset, value)` for direct register writes by address offset (0x00–0x18)
- `SoundInterfaceDevice.clock(timedelta)` → `list[int]` signed 16-bit PCM samples
- `SID.clock(cycles)` for precise cycle-level control
- `PAL_CLOCK_FREQUENCY = 985248.0`, `NTSC_CLOCK_FREQUENCY = 1022730.0` (constants)
- `Filter_Mode_Vol` at 0x18, bits 0-3 = volume (0-15)

**Audio output** — `sounddevice` (PyPI 0.5.5). `RawOutputStream` with `int16` callback.
Well-documented, non-blocking.

### 5. Research Complete — PASS

**Previous blocker resolved.** All three dependencies researched and validated:
- `pyresidfp` 0.17.0: confirmed on PyPI, API verified against source
- `py65emu` 0.1.0: confirmed on PyPI, API verified (TXC fork, not docmarionum1)
- `sounddevice` 0.5.5: confirmed on PyPI

Performance risk acknowledged in requirements: `py65emu` is pure Python and may be slow.
Mitigation documented: pre-buffer several seconds ahead. Fallback documented: `sidplayfp`
CLI (Homebrew) writing to temp WAV. This is an acceptable risk for v1.

### 6. Dependencies & Preconditions — PASS

- No blocking todos in the roadmap.
- HVSC collection confirmed at `assets/audio/C64Music/` (DEMOS, MUSICIANS, GAMES, etc.).
- System deps: PortAudio (`brew install portaudio`) for `sounddevice`.
- Python deps: `pyresidfp>=0.17.0`, `py65emu>=0.1.0`, `sounddevice>=0.5.5` — all on PyPI.
- No new config wizard entries needed (chiptunes config is optional/additive).

### 7. Integration Safety — PASS

New module (`teleclaude/chiptunes/`) is additive. Existing code modifications follow
proven patterns (validated against codebase in previous gate round):
- `runtime_settings.py` — extend `SettingsState`, `SettingsPatch`, `parse_patch()`,
  `_flush_to_disk()` (confirmed extensible at lines 29-161)
- `api_models.py` — add `ChiptunesSettingsPatchDTO`, extend `SettingsPatchDTO`/`SettingsDTO`
  (follows `TTSSettingsDTO` pattern at lines 417-446)
- `telec_footer.py` — add reactive property, icon, click handler
  (follows `tts_enabled` pattern at line 33)
- `app.py` — add `Binding("m", ...)` (keybinding `m` confirmed no conflict)
- `messages.py` — extend `DataRefreshed` (follows `tts_enabled` field pattern at line 30)
- Feature behind `chiptunes.enabled` (default: off). Import guards for graceful degradation.

### 8. Tooling Impact — N/A

No scaffolding or tooling changes required.

## Plan-to-Requirement Fidelity

All requirements trace to plan tasks:

| Requirement | Plan Task(s) |
|---|---|
| SID playback engine (3-layer pipeline) | 1.1, 1.2, 1.3, 1.4 |
| ChiptunesManager | 1.5 |
| Runtime settings integration | 2.1 |
| Config section | 2.2 |
| API endpoint | 2.3 |
| TUI footer icon | 3.1 |
| TUI keybinding | 3.2 |
| Click toggle | 3.1 (click region) |
| Track rotation | 1.5 (auto-advance) |
| TTS coexistence | 4.1 |
| RSID exclusion | 1.1 (reject), 1.5 (filter) |
| Dependency setup | 1.6 |

No plan task contradicts a requirement. No requirement is missing from the plan.

## Actions Taken (This Gate Round)

1. Fixed `write()` → `cpu_write()` in plan Task 1.2 (PyPI `py65emu` TXC fork API).
2. Fixed NTSC clock frequency `1022727` → `1022730` Hz in plan Task 1.3 (matches
   `SoundInterfaceDevice.NTSC_CLOCK_FREQUENCY` constant).
3. Added `SoundInterfaceDevice.clock(timedelta)` return type detail and `SID.clock(cycles)`
   alternative to plan Task 1.3.
4. Added `PAL_CLOCK_FREQUENCY`/`NTSC_CLOCK_FREQUENCY` constant references to plan Task 1.3.

## Blockers

None.

## Risks (Acknowledged, Not Blocking)

1. **py65emu performance**: pure-Python 6502 may not sustain real-time for complex tunes.
   Mitigation: pre-buffer 2-3 seconds. Fallback: `sidplayfp` CLI subprocess.
2. **Kernal ROM**: some tunes need `$E000–$FFFF` ROM routines. Skip and advance on error.
3. **CIA timer tunes**: speed flag bit = 1 tunes deferred to post-v1.
