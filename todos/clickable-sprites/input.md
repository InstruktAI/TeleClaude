# clickable-sprites — Input

## Clickable Animation Sprites — Open Source on GitHub

### Vision
The TUI displays animated sprites (C64-era pixel art, animations). Each sprite/animation asset originates from an open-source repository or resource on GitHub. The user wants to click on a sprite in the TUI and have it open the browser to the GitHub page for that specific resource — the source repo, the specific file, or the asset's origin page. This turns the decorative sprites into discoverable, attributable links back to the community that created them.

### Requirements
1. **Clickable sprite area** — the sprite/animation widget in the TUI should respond to mouse clicks. When clicked, it opens the default browser with the URL pointing to the resource's GitHub origin.
2. **URL mapping** — each animation/sprite asset needs an associated source URL. This could be stored as metadata alongside the animation files, in a manifest, or as an attribute on the animation config. The URL should point to the most specific location possible: the repo, the specific file, or the release page.
3. **Browser launch** — on click, use the platform's default browser opener (webbrowser.open or equivalent). Should work on macOS (open), Linux (xdg-open), and other platforms.
4. **Visual affordance** — optionally, indicate that the sprite is clickable (e.g. cursor change on hover, subtle underline, or tooltip showing the URL). This is a nice-to-have — the primary requirement is just that clicking works.
5. **Attribution spirit** — this feature serves both UX (discovery, curiosity) and attribution (crediting the open-source creators of the pixel art and animation assets used in the TUI).

### Technical context
- Animations are rendered in the TUI via Textual widgets
- The animation toast was recently disabled (_show_animation_toast is a no-op) — the clickable sprite replaces that as the discovery mechanism
- Need to audit current animation assets to determine their GitHub source URLs
- Textual widgets support on_click handlers and mouse events
