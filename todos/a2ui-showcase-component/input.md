# A2UI Showcase Component — First Widget Proof of Concept

## Context

Research into the A2UI protocol (Google) revealed a strong architectural fit for TeleClaude's vision of framework-agnostic, agent-discoverable UI components. A2UI defines a declarative component specification where agents emit JSON describing widgets, and clients render them natively using their own catalog implementations.

This todo delivers the **first working component** to prove the entire chain: catalog discovery, API-driven data, web component rendering, theming, and A2UI-compatible output.

## The Feature

Build `<teleclaude-showcase>`, a web component that demonstrates TeleClaude's identity and capabilities, rendered in a standalone HTML demo file with live API data and real-time theme switching.

### What we deliver

1. **Web Component** (`teleclaude-showcase`)
   - Custom Element using Shadow DOM for style encapsulation
   - Fetches content from a configurable API endpoint
   - Renders rich content: project info, GitHub links, capabilities
   - Themed via CSS custom properties that map to Tailwind variables
   - Graceful fallback when JS is disabled (slot-based progressive enhancement)

2. **API Endpoint** (`GET /api/widgets/showcase`)
   - Daemon endpoint that serves widget data
   - Content driven by a config file (easy to update for YouTube demos, presentations)
   - Returns JSON matching the component's data schema

3. **Demo HTML Runner** (`widgets/demo.html`)
   - Single static HTML file — no build step, no framework
   - Loads the component, connects to API
   - Theme control panel: modify CSS variables in real-time
   - Shows 2-3 side-by-side instances with different theme presets (dark, light, branded)
   - Shows the equivalent A2UI JSON description inline (proves format compatibility)

4. **Component Catalog** (first entry)
   - Index file establishing the catalog format (like `docs/index.yaml` for widgets)
   - Entry for `teleclaude-showcase` with ID, description, schema, and renderer path
   - Discoverable by agents via `get_context` or future component discovery tool

### Component content (configurable)

- Project name and tagline
- GitHub repository URL (rich link to README)
- Key capabilities (multi-computer orchestration, AI agent sessions, etc.)
- Links: docs, releases, license
- Optional: live session count or computer count from daemon cache

### Theme demonstration

The demo must prove that a single component can be restyled by the client without touching component code:

- CSS custom properties: `--tc-primary`, `--tc-bg`, `--tc-surface`, `--tc-text`, `--tc-radius`, `--tc-font`
- Default values map to Tailwind defaults
- Theme panel in demo allows real-time modification
- At least 3 preset themes shown side-by-side

### A2UI format demonstration

The demo should also render the A2UI JSON that would describe this component, proving the format works:

```json
{
  "surfaceUpdate": {
    "surfaceId": "teleclaude-showcase-1",
    "components": [
      {
        "id": "showcase",
        "component": {
          "TeleClaudeShowcase": {
            "apiUrl": "/api/widgets/showcase"
          }
        }
      }
    ]
  }
}
```

## What this proves

- Web components work as framework-agnostic delivery mechanism
- API-driven content decouples widget from hardcoded data
- CSS custom properties enable white-label theming
- Component catalog pattern is viable for cross-project widget discovery
- A2UI specification format can describe our widgets
- The transport (websocket/text stream) doesn't need to change — just include component references

## Dependencies

- Daemon API server (exists — add new endpoint)
- A2UI research docs (exists — `docs/third-party/a2ui/overview.md`)
- Web component standards (browser-native, no dependencies)

## Out of scope

- Integration with the actual Next.js web frontend (doesn't exist yet)
- Agent-side component discovery tool (future work)
- Streaming/progressive rendering (future — this is a static component)
- Multiple components (this delivers exactly one as proof)
- Telegram/TUI rendering of A2UI blocks (future)

## Related research

- `~/.teleclaude/explore/ag-ui-a2ui/` — AG-UI + A2UI research and fit assessment
- `docs/third-party/a2ui/overview.md` — A2UI specification reference
- `docs/third-party/ag-ui/overview.md` — AG-UI event protocol reference
