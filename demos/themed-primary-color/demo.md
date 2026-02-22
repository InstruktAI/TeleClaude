# Demo: Agent-Variant Themes with Warm Primary Color

## Validation

Verify the theme module loads and exposes the expected theme objects.

```bash
python -c "from teleclaude.cli.tui.theme import _TELECLAUDE_DARK_AGENT_THEME, _TELECLAUDE_LIGHT_AGENT_THEME; print('Agent themes loaded')"
```

Verify the base themes are also available.

```bash
python -c "from teleclaude.cli.tui.theme import _TELECLAUDE_DARK_THEME, _TELECLAUDE_LIGHT_THEME; print('Base themes loaded')"
```

Verify the theme module exposes the appearance detection API.

```bash
python -c "from teleclaude.cli.tui.theme import _get_env_appearance_mode; mode = _get_env_appearance_mode(); print(f'Appearance mode: {mode}')"
```

## Guided Presentation

Launch `telec` and navigate to the TUI. The theme system introduces warm orange tones at agent-level theming.

Start at **Level 0 (default)** — the peaceful, neutral gray palette. This is the calm base. Then navigate the carousel widget to the **agent level** — Claude's warm orange (`#d7af87` dark, `#875f00` light) becomes the primary color. Headers, accents, and focus indicators shift to orange. Toggle back and forth to see the transition.

The theme system detects dark/light mode from macOS system settings and applies the correct variant automatically. The agent-variant themes inherit all base variables and override only the primary color, keeping the visual language consistent while adding personality at higher engagement levels.
