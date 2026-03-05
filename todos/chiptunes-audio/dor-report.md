# DOR Report: chiptunes-audio

## Gate Assessment

**Phase**: Gate (formal DOR validation)
**Assessed at**: 2026-03-05
**Verdict**: needs_work

## Gate Analysis

### 1. Intent & Success — PASS

Problem statement is clear: add background ChipTunes music playback using SID files
from the HVSC collection, toggled via TUI and API. Success criteria are concrete and
testable (keybinding works, icon changes, audio plays, persistence works, TTS coexistence).

### 2. Scope & Size — PASS (with note)

Touches multiple layers (new module, config, API, TUI widgets, TTS coexistence) but
follows proven patterns. Phase decomposition in the plan helps manage the scope.
Fits a single focused session.

### 3. Verification — PASS

Unit tests defined for player, manager, settings, API. Integration test for TTS
coexistence. Manual demo plan covers the full user journey. `make test` and `make lint`
as quality gates.

### 4. Approach Known — FAIL

**Critical finding: the SID decoding path is not validated.**

- `libsidplayfp` Python bindings (`libsidplayfp-python`) are **NOT on PyPI**. Installation
  requires compiling from source with a C/C++ compiler, `cffi >= 1.0.0`, and `libsidplayfp >= 1.8`
  system library. The package is alpha quality (v0.0.7a0), has 33 commits, and is only tested
  on GNU/Linux — **not macOS**, which is the target platform.

- `pyresidfp` IS on PyPI (v0.17.0), but it is a **low-level SID chip register emulator** — it
  does NOT load `.sid` files. Its API exposes `attack_decay()`, `sustain_release()`, `tone()`,
  `control()`, and `clock()` methods for direct register manipulation. To play a `.sid` file,
  you would need a 6502/6510 CPU emulator to interpret the embedded machine code and translate
  it into register writes. `pyresidfp` is not a drop-in fallback for `libsidplayfp`.

- The implementation plan Task 1.1 states: "Callback function: decode SID frames via
  libsidplayfp/pyresidfp, fill int16 buffer." This cannot work as written with either library.

The requirements state: "Use libsidplayfp Python bindings (or pyresidfp if the former is
unavailable on PyPI)." This fallback is invalid because the two libraries have fundamentally
different APIs and capabilities.

**Viable alternatives to investigate:**

1. **`sidplayfp` CLI via subprocess** — install via Homebrew (`brew install libsidplayfp`),
   pipe audio output to `sounddevice` or a temp WAV file. Simplest path but adds a system
   binary dependency and subprocess overhead.
2. **Pre-convert `.sid` → WAV/OGG** — batch-convert HVSC collection offline, play standard
   audio formats with `sounddevice`. Removes the SID decoding problem entirely but increases
   storage and requires an upfront conversion step.
3. **Compile `libsidplayfp-python` from source** — install `libsidplayfp` via Homebrew,
   then pip install from GitHub. Riskiest: alpha quality, macOS untested, may crash the
   interpreter.

### 5. Research Complete — FAIL

The draft report noted this as "needs verification" but the builder was expected to spike
it during Task 1.3. This is insufficient for DOR: the core technical approach must be
validated before entering build. A builder receiving this plan would discover the library
mismatch in the first 15 minutes and have to redesign the architecture.

Research needed:
- Confirm which SID-to-PCM approach works on macOS.
- Validate the chosen library's API against the player design.
- Update requirements and implementation plan to reflect the actual library.

### 6. Dependencies & Preconditions — PASS (conditional)

- No blocking todos in the roadmap.
- HVSC collection confirmed at `assets/audio/C64Music/` (subdirs: DEMOS, MUSICIANS, GAMES, etc.).
- `sounddevice` confirmed on PyPI (v0.5.5).
- System deps: PortAudio (macOS: `brew install portaudio`) — well-documented.
- The SID library dependency itself is unresolved (see gate 4).

### 7. Integration Safety — PASS

- New module (`teleclaude/chiptunes/`) is additive.
- Existing code modifications are minimal and follow proven patterns:
  - `runtime_settings.py` — extend with chiptunes section (TTS pattern confirmed: `TTSSettings`,
    `TTSSettingsPatch`, `SettingsPatch`, `parse_patch()`, `_flush_to_disk()` all clearly
    extensible).
  - `api_models.py` — extend `SettingsDTO`/`SettingsPatchDTO` (same pattern as `TTSSettingsDTO`/
    `TTSSettingsPatchDTO`).
  - `telec_footer.py` — add icon (same pattern as `tts_enabled` reactive + watch).
  - `app.py` — add keybinding (keybinding `m` confirmed no conflict, `Binding("v", ...)` pattern).
  - `messages.py` — extend `DataRefreshed` (currently has `tts_enabled: bool`).
- Feature behind `chiptunes.enabled` flag (default: off). Rollback: remove module + revert.

### 8. Tooling Impact — N/A

No scaffolding or tooling changes required.

## Confirmed Codebase Patterns

The gate validation confirmed these implementation anchors:
- `RuntimeSettings` at `teleclaude/config/runtime_settings.py` — clean extension point.
- `SettingsState`, `SettingsPatch`, `parse_patch()` — typed patch flow works.
- `TTSSettingsDTO`/`TTSSettingsPatchDTO` at `teleclaude/api_models.py:417-446` — API model pattern.
- `telec_footer.py` — `tts_enabled = reactive(False)`, icon rendering, click handler.
- `app.py:134` — `Binding("v", "toggle_tts", "Voice")` keybinding pattern.
- `messages.py:19-39` — `DataRefreshed` constructor with `tts_enabled` field.

## Plan-to-Requirement Fidelity Issues

1. **Requirements say** "Use libsidplayfp Python bindings (or pyresidfp if the former is
   unavailable on PyPI)" — **plan says** "decode SID frames via libsidplayfp/pyresidfp."
   Both are based on the false assumption that `pyresidfp` can load `.sid` files. The plan
   faithfully follows the requirements, but the requirements themselves are wrong.

## Blockers

1. **SID decoding library**: The core playback technology is unvalidated. Neither
   `libsidplayfp` (not on PyPI, alpha, Linux-only) nor `pyresidfp` (register-level emulator,
   cannot load `.sid` files) work as specified. Requirements and implementation plan must be
   revised to use a validated approach.

## Required Remediation

1. Research and validate a working SID → PCM approach on macOS.
2. Update `requirements.md` to specify the actual library/approach.
3. Update `implementation-plan.md` Task 1.1 and 1.3 to reflect the validated API.
4. Re-submit for gate validation.
