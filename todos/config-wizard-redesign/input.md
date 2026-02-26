# Input: config-wizard-redesign

## Problem

The config wizard is the primary interface for operators setting up TeleClaude. It currently looks and feels like a placeholder — read-only status lists with no visual hierarchy, no inline editing, and no guided onboarding flow. For a product that manages multiple communication adapters (Telegram, Discord, WhatsApp), AI keys, people, notifications, and environment variables, the config experience is a critical UX surface that directly affects first impressions and operational confidence.

This is not a cosmetic issue. The wizard is the gateway to every adapter. If it's ugly and unhelpful, operators fall back to manual YAML editing, which defeats the purpose.

## Current State

### Architecture (two parallel views)

| View           | Framework    | File                                                    | Active In   |
| -------------- | ------------ | ------------------------------------------------------- | ----------- |
| Legacy curses  | Raw curses   | `teleclaude/cli/tui/views/configuration.py` (259 lines) | Curses TUI  |
| Modern Textual | Textual/Rich | `teleclaude/cli/tui/views/config.py` (301 lines)        | Textual TUI |

Both share `config_handlers.py` as the data layer. Both render independently.

### What the wizard can do today

- Tab between sections: Adapters, People, Notifications, Environment, Validate
- Within Adapters: sub-tab between Telegram, Discord, AI Keys, WhatsApp
- Show env var status (checkmark/cross) with description and example
- Show people list (name, role, email)
- Run validation checks
- "Guided mode" that Tab-walks through sections (no actual guidance)

### What the wizard cannot do

- **Edit values** — no input fields, no shell prompts, no env var setting
- **Guide setup** — guided mode shows status but doesn't help the user complete steps
- **Show visual hierarchy** — everything is a flat list
- **Progressive disclosure** — all info shown at once, no collapsed/expanded sections
- **Indicate completion** — no progress bar, no "3 of 5 adapters configured" summary
- **Notifications tab** — shows "(Not implemented yet)" literally

### Specific rendering issues

- Curses: hardcoded scroll heuristic (`selected_index > scroll_offset + 5`), 4-line fixed guidance panel, emoji rendering on non-UTF8 terminals
- Textual: plain Rich Text output, no Textual widgets (Input, Button, DataTable), no reactive state for editing
- Both: no color theming beyond basic dim/reverse/green/red

### Component architecture (solid foundation)

- `ConfigComponent` abstract base: `render()`, `handle_key()`, `get_section_id()`, `get_animation_state()`
- `ConfigComponentCallback` protocol for animation/redraw coordination
- `EnvVarInfo` / `EnvVarStatus` data classes
- `GuidanceRegistry` with `FieldGuidance` (description, steps, url, format_example, validation_hint)
- `ValidationResult` with area/passed/errors/suggestions

The data layer and component abstraction are ready — the rendering and interaction layer is what needs redesign.

## Vision

The config wizard should be the **single best way** to set up TeleClaude. An operator should be able to go from zero to fully configured using only the wizard.

### UX Goals

1. **Visual clarity** — each adapter is a card/section with clear status (configured/partial/unconfigured), grouped env vars, and inline guidance
2. **Inline editing** — edit env var values directly in the TUI, saved to `.env` on confirm
3. **Guided onboarding** — a real step-by-step flow that walks through each adapter, checks prerequisites, and celebrates completion
4. **Progress visibility** — overall config health score, per-adapter completion percentage, clear "what's missing" indicators
5. **Notifications tab** — either implement it or remove the dead tab
6. **Consistent framework** — consolidate on Textual (the curses view can be deprecated or kept as fallback)

### Interaction Model

- Tab/arrow navigation stays (keyboard-first for terminal operators)
- Enter on an env var opens an inline edit field
- Guidance panel shows provider-specific setup steps (links, format examples, validation)
- Validation runs automatically when values change
- Visual feedback on save (success/error)

## Success Criteria

1. An operator can configure a new adapter entirely through the wizard (no manual YAML editing required for standard setup)
2. Each adapter section shows clear visual status: configured (all vars set), partial (some vars set), unconfigured (no vars set)
3. Env vars can be edited inline with immediate persistence to `.env`
4. Guided mode walks through adapters sequentially with per-step guidance and validation
5. Overall config health is visible at a glance (e.g., "4/5 sections configured")
6. The notifications tab either works or is removed
7. Visual design is intentional — cards/sections with clear hierarchy, not flat lists

## Key Files

- `teleclaude/cli/tui/views/config.py` — Textual view (primary target)
- `teleclaude/cli/tui/views/configuration.py` — curses view (secondary/deprecation candidate)
- `teleclaude/cli/tui/config_components/` — all component classes
- `teleclaude/cli/config_handlers.py` — shared data layer
- `teleclaude/cli/tui/config_components/guidance.py` — setup guidance registry

## Notes

This is a **major UX initiative**, not a quick fix. The config wizard is the operator's first and most frequent touchpoint with TeleClaude's administrative surface. Design it accordingly — with the same care we'd give a customer-facing product page.
