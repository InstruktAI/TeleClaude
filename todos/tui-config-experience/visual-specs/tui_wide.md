# TUI Wide Specs

## Tab Transition

- **Scroll:** Tabs slide left/right when switching.
- **Motion:** Smooth ease-in/out.

## Depth Layering

- **Concept:** Active tab is z-index 10, inactive tabs are z-index 0.
- **Implementation:** Draw inactive tabs first, then active tab on top with shadow.

## Three-Mode Toggle

- **Off:** No animations.
- **Periodic:** Current behavior (occasional triggers).
- **Party:** Constant activity, shorter intervals, all idle animations active.
