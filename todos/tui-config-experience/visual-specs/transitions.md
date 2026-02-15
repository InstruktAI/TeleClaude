# Tab Transitions & Depth Layering — Concept Doc

## Tab Transitions

### Cross-Fade (all modes)

When switching tabs, the current banner colors fade to -1 over 3 frames,
then the new tab's colors fade in over 3 frames. Simple dissolve.

- Total duration: 0.3s (6 frames at 50ms)
- No directional bias
- Clean and predictable
- Used in both PERIODIC and PARTY modes (consistent, no confusion)

## Depth-Layered Rendering

### Z-Layer Architecture

```
z=0: Background (terminal default)
z=1: Banner text + banner color animations
z=2: Inactive tab labels (subdued, muted color)
z=3: Scene animation characters (bicycle, cat, scroller)
z=4: Active tab label + border (bold, always on top)
```

### Rendering Order

The tab bar renderer draws bottom-up by z-order:

1. Draw the base line (`─────────`) at z=0
2. Draw inactive tab labels at z=2
3. Consult SceneOverlay for any characters at z=3 → draw on top of z=2
4. Draw active tab label + border at z=4 → covers anything below

### Parallax Effect

Scene characters (bicycle, cat) ride across the tab bar line:

- When passing through inactive tab regions → scene character visible (z=3 > z=2)
- When passing through active tab region → scene character hidden (z=3 < z=4)

This creates genuine depth perception — objects passing between foreground
and background layers.

### Implementation Notes

- The existing TabBar.render() draws all 3 rows of the tab bar
- Scene overlay integration point: after drawing row 3 (the line), check
  SceneOverlay for characters at each position
- Only render scene character if its z-level > the current element's z-level
- Active tab region must be drawn LAST (z=4, always wins)
