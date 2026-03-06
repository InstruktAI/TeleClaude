# Demo: chiptunes-playlist-controls

## Validation

```bash
# Verify favorites file operations
python -c "
from teleclaude.chiptunes.favorites import load_favorites, save_favorite, is_favorited
# Should be empty or existing
favs = load_favorites()
print(f'Favorites count: {len(favs)}')
# Save a test favorite
save_favorite('Test Track', '/tmp/test.sid')
assert is_favorited('/tmp/test.sid'), 'Should be favorited'
print('Favorites persistence: OK')
"
```

```bash
# Verify new API endpoints respond
curl -s -X POST --unix-socket /tmp/teleclaude-api.sock http://localhost/api/chiptunes/next | python -m json.tool
curl -s -X POST --unix-socket /tmp/teleclaude-api.sock http://localhost/api/chiptunes/prev | python -m json.tool
```

```bash
# Run chiptunes tests
make test -- tests/unit/test_chiptunes.py -v
```

## Guided Presentation

### Step 1: Start chiptunes via footer
Click the ▶ icon in the footer (or press `m` to enable chiptunes). Observe:
- The icon group appears: ⏮ ⏸ ⏭ ⭐
- A "Now Playing" toast shows the track name
- The ⏸ icon indicates playback is active

### Step 2: Navigate tracks
Click ⏭ to skip to the next track. Observe:
- A new "Now Playing" toast with the new track name
- Click ⏮ to go back — the previous track resumes
- Click ⏮ again at the start of history — nothing happens (boundary)

### Step 3: Pause and resume
Click ⏸ to pause. Observe:
- Audio stops, icon changes to ▶
- Click ▶ to resume — audio resumes, icon changes back to ⏸

### Step 4: Favorite a track
While a track is playing, click ⭐. Observe:
- Icon changes to ✅ (track saved)
- Navigate away and back — ✅ persists for favorited tracks
- Check `~/.teleclaude/chiptunes-favorites.json` — entry exists with track name, SID path, timestamp

### Step 5: Verify on narrow terminal
Resize terminal to 80 columns. Observe:
- All four player icons remain visible and clickable
- No overflow or layout breakage
