# Demo: chiptunes-audio

## Validation

```bash
# Verify chiptunes module exists and imports cleanly
python -c "from teleclaude.chiptunes.manager import ChiptunesManager; print('OK')"
```

```bash
# Verify runtime settings accept chiptunes patch
python -c "
from teleclaude.config.runtime_settings import RuntimeSettings
patch = RuntimeSettings.parse_patch({'chiptunes': {'enabled': True}})
assert patch.chiptunes is not None
assert patch.chiptunes.enabled is True
print('Settings patch OK')
"
```

```bash
# Verify API accepts chiptunes settings patch
curl -s --unix-socket /tmp/teleclaude-api.sock \
  -X PATCH http://localhost/settings \
  -H 'Content-Type: application/json' \
  -d '{"chiptunes": {"enabled": true}}' | python -m json.tool
```

```bash
# Verify .sid files are discoverable
python -c "
from pathlib import Path
sids = list(Path('assets/audio/C64Music').rglob('*.sid'))
print(f'Found {len(sids)} .sid files')
assert len(sids) > 1000
"
```

## Guided Presentation

### Step 1: Show the TUI footer icons

Open the TUI (`telec`). Observe the bottom status bar:
- The **speaker icon** (🔊/🔇) now represents **ChipTunes** — not TTS.
- TTS has a new **speech icon** (🗣️) next to it.
- Both icons reflect their enabled/disabled state independently.

### Step 2: Toggle chiptunes with keyboard

Press `m` in the TUI. Observe:
- The speaker icon lights up (🔊 bold).
- A random C64 SID track begins playing through your speakers.
- The track name is not displayed (shuffle mode — no UI for track info in v1).

### Step 3: Verify auto-advance

Wait for the current track to end (SID tracks are typically 2-5 minutes).
A new random track should start automatically without user intervention.

### Step 4: Toggle off

Press `m` again. Observe:
- Audio stops immediately.
- The speaker icon dims (🔇).

### Step 5: Click toggle

Click the speaker icon in the footer. Same behavior as pressing `m`.

### Step 6: TTS coexistence

Enable both chiptunes (`m`) and TTS (`v`). Trigger a TTS event
(e.g., start a new agent session). Observe:
- Chiptunes audio pauses when TTS speaks.
- Chiptunes resume after TTS completes.

### Step 7: Persistence

Toggle chiptunes on, then restart the TUI (kill -USR2). After restart,
verify chiptunes are still enabled and playback resumes.

### Step 8: API toggle

```bash
# Enable via API
curl -s --unix-socket /tmp/teleclaude-api.sock \
  -X PATCH http://localhost/settings \
  -H 'Content-Type: application/json' \
  -d '{"chiptunes": {"enabled": false}}'
```

Verify audio stops and the footer icon updates.
