# Requirements: clickable-sprites

## Goal

Make TUI sprites an open, contributor-friendly system: anyone can create a sprite,
drop it in, run `telec`, and immediately see it working — or get a clear, actionable
error message explaining what's wrong. Then make each sprite clickable so it links
back to its GitHub source for attribution and discovery.

## Scope

### In scope

1. **Sprite validation on TUI startup** — when the TUI loads sprites via
   `get_sky_entities()`, catch and surface malformed sprite errors as visible
   terminal output (not just log-file entries). The user must see what went
   wrong and which file caused it.

2. **Graceful TUI startup without daemon** — the TUI currently starts via
   `telec config wizard` without requiring the daemon. Ensure the sprite/animation
   system does not crash when the daemon socket is absent or the log directory
   (`/var/log/instrukt-ai/teleclaude/`) does not exist. Degrade gracefully:
   animations work, data views show "connecting..." or empty state.

3. **Source URL metadata on sprites** — add an optional `source_url` field to
   `CompositeSprite` and `AnimatedSprite` in `composite.py`. This holds the
   GitHub URL (repo, file, or release page) for the sprite's origin. Populate
   it for all existing sprites with their actual source URLs.

4. **Clickable sprite area in Banner** — when the user clicks on a region of
   the Banner widget where a sky entity is rendering, open the sprite's
   `source_url` in the default browser via `webbrowser.open()`. This replaces
   the disabled `_show_animation_toast` as the sprite discovery mechanism.

5. **Simple authoring instructions** — document how to create a new sprite
   (file format, naming, required fields, how to test) in a contributor-facing
   file that gets included in the repo.

### Out of scope

- New sprite artwork creation (existing sprites get URLs, but no new sprites are commissioned).
- Cursor change or hover tooltip on sprites (nice-to-have, deferred).
- Sprite hot-reload without TUI restart (deferred).
- Any changes to the animation engine's rendering pipeline.

## Success Criteria

- [ ] A malformed sprite (e.g., mismatched layer dimensions, invalid color) produces
      a visible error message on `telec` startup that names the file and the error.
- [ ] Running `telec` without the daemon running shows the TUI with animations
      working, data views gracefully empty — no crash, no traceback.
- [ ] Running `telec` when `/var/log/instrukt-ai/teleclaude/` does not exist does
      not crash — logging degrades to stderr or is silently suppressed.
- [ ] All existing sprites in `teleclaude/cli/tui/animations/sprites/` have a
      `source_url` field pointing to their GitHub origin.
- [ ] Clicking on a visible sprite in the Banner area opens the browser to the
      sprite's `source_url`.
- [ ] A contributor can follow the authoring instructions, create a new sprite file,
      and see it appear in the TUI by running `telec`.

## Constraints

- The Banner widget uses Rich `Text` rendering — click handling must use Textual's
  mouse event system, not Rich's.
- Sprite files are Python modules auto-discovered via `__init__.py` `__all__` —
  new sprites must follow this convention.
- The `CompositeSprite` and `AnimatedSprite` dataclasses are frozen — `source_url`
  must be added as an optional field with a default.
- `webbrowser.open()` is the platform-agnostic browser opener — no shelling out
  to `open` or `xdg-open` directly.

## Risks

- Sprite hit detection in the Banner is approximate — the Banner renders
  character-by-character with animation overlays. Mapping click coordinates
  to sky entities requires knowing which entity occupies which pixel region,
  which the animation engine's Z-buffer already tracks.
- Some sprites are community-sourced — verifying the correct GitHub source URL
  for each existing sprite requires manual audit.
