# Requirements: chiptunes-playlist-controls

## Goal

Replace the single chiptunes toggle icon in the TUI footer with a four-button player control group (⏮️⏯️⏭️⭐) and add persistent favorites. The player maintains session-scoped track history so users can navigate back to songs they liked.

## Scope

### In scope

- Footer player control group: prev, play/pause, next, favorite
- Worker-side track history for prev/next navigation
- New worker commands: `next`, `prev`
- Manager proxy methods for `next()` and `prev()`
- Persistent favorites file (`~/.teleclaude/chiptunes-favorites.json`)
- Stateful favorite button (⭐ → ✅ when current track is favorited)
- Footer reactive state: current track name, paused state, favorited state
- WebSocket event enrichment: track event must carry SID filename for favorites matching

### Out of scope

- Persistent playback history across worker restarts (history is session-scoped)
- Playlist editing UI (reorder, remove individual entries)
- Shuffle/repeat mode toggles
- Volume control in footer
- Custom toast widgets or action buttons in notifications
- Remove-from-favorites via ✅ click (initial: ✅ is a no-op)

## Success Criteria

- [ ] Footer shows ⏮️⏯️⏭️⭐ when chiptunes is enabled (dim when disabled)
- [ ] ⏯️ starts playback when chiptunes is off, toggles pause/resume when on
- [ ] ⏯️ visually reflects state: ⏸️ when playing, ▶️ when paused
- [ ] ⏭️ advances to next track (new random if at end of history)
- [ ] ⏮️ goes back to previous track in history
- [ ] ⭐ saves current track to `~/.teleclaude/chiptunes-favorites.json`
- [ ] ⭐ shows ✅ when current track is already in favorites
- [ ] Track history is maintained in worker process across prev/next navigation
- [ ] Existing "Now Playing" toast continues to work unchanged
- [ ] All existing chiptunes tests pass; new behavior is covered by tests

## Constraints

- Footer height remains 3 lines — controls must fit in the existing controls row
- Worker protocol is JSON lines over Unix socket — new commands follow same pattern
- Favorites file is local to the machine (not synced, not daemon-managed)
- The TUI reads/writes favorites directly (no API endpoint needed — file is local)
- Track history lives only in the worker process; daemon restart loses it (acceptable)

## Risks

- Footer width: four icons + spacing may crowd the controls row on narrow terminals. Mitigation: use compact single-char icons, test at 80-col width.
- Textual click regions: each icon needs its own click region tracked by x-coordinate (same pattern as existing toggles). Complexity is manageable since it follows established patterns.
