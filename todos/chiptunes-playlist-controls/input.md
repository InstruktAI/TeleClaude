# chiptunes-playlist-controls — Input

## Chiptunes Player Controls & Favorites

### Vision
Replace the single chiptunes toggle icon (🔊/🔇) in the TUI footer with a proper player control group: ⏮️⏯️⏭️⭐. The user can navigate tracks (prev/next), play/pause, and star favorites. The current playback session maintains a track history so users can go back to songs they liked. The ⭐ button is stateful — it shows ✅ when the current track is already in the user's favorites list.

### Requirements
1. **Player control icons in footer** — replace the current single 🔊/🔇 toggle with a group of four clickable icons: ⏮️ (previous track), ⏯️ (play/pause toggle), ⏭️ (next track), ⭐ (save to favorites). Icons should be dim when chiptunes is disabled.
2. **Track history (session playlist)** — the worker must maintain an ordered history of played tracks so the user can navigate back. Currently it picks random tracks with no memory. The history is ephemeral (lives in the worker process, not persisted). Prev goes back in history; next either advances forward in history or picks a new random track if at the end.
3. **Play/pause toggle** — ⏯️ toggles between pause and resume. When chiptunes is off entirely, clicking ⏯️ should start playback (enable chiptunes). Visual state: show ⏸️ when playing, ▶️ when paused.
4. **Favorites persistence** — a persistent file (JSON) where favorited tracks accumulate. Location: `~/.teleclaude/chiptunes-favorites.json`. Each entry: track name, SID filename, timestamp saved.
5. **Stateful ⭐ button** — when the currently playing track is already in the favorites list, show ✅ instead of ⭐. Clicking ⭐ adds to favorites (with visual feedback). Clicking ✅ could either do nothing or remove from favorites (TBD — simpler to make it a no-op initially).
6. **Now Playing toast** — keep the existing toast notification when a new track starts. The toast already works via ChiptunesTrackEvent -> notify(). No action buttons needed in the toast since the footer controls handle everything.

### Technical context
- Current toggle: single 🔊/🔇 icon in `telec_footer.py`, click posts `SettingsChanged("chiptunes_enabled", ...)`.
- Manager has `pause()`/`resume()` but they're not exposed in the TUI.
- Worker picks random tracks via `_play_random()` with no history — needs `next`/`prev` commands and a history list.
- Manager needs new commands: `next`, `prev` forwarded to worker.
- ChiptunesTrackEvent already broadcasts track name over WebSocket to TUI.
- Footer needs to know current track name and whether it's in favorites to render ⭐/✅.
