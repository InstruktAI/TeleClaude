# Requirements: a2ui-showcase-component

## Goal

Build a public-facing `/showcase` page in the Next.js frontend that presents TeleClaude's identity, capabilities, and live system stats. The page is API-driven (content from daemon), theme-aware, and shareable as a standalone URL for demos, presentations, and external audiences.

## Scope

### In scope:

1. **Showcase page** (`frontend/app/showcase/page.tsx`) — a client component that fetches content from the daemon and renders a presentation-quality layout. Public route, no authentication required.

2. **Daemon API endpoint** (`GET /api/showcase`) — serves structured showcase content as JSON. Includes static identity data (name, tagline, capabilities, links) from configuration and live stats (computer count, session count, project count) from daemon cache.

3. **Next.js API proxy route** (`frontend/app/api/showcase/route.ts`) — proxies to the daemon endpoint. No auth guard (public page).

4. **Showcase configuration** — a dedicated config section or file that drives the content. Editable without code changes (for YouTube demos, presentations, investor pitches).

5. **Theme demonstration** — toggle between dark/light themes on the page using the existing CSS variable token system (`lib/theme/tokens.ts`, `lib/theme/css-variables.ts`).

6. **Reusable presentation components** — hero section, capability cards, stat block, link list. Built as composable React components that future pages (e.g., `/demos/[slug]`) can reuse.

### Out of scope:

- Agent-triggered rendering (this is a browser-visited URL, not a widget expression)
- Demo artifact viewer (`/demos/[slug]` belongs to `next-demo` todo)
- Widget SDK integration on the page itself
- Authentication or role-based access (page is public)
- Animation canvas integration (future enhancement)
- Telegram/TUI rendering of showcase content
- Internationalization

## Success Criteria

- [ ] `GET /showcase` renders a responsive page with hero, capabilities, stats, and links
- [ ] Content is fetched from daemon API, not hardcoded in the frontend
- [ ] Daemon endpoint returns showcase JSON including live stats from cache
- [ ] Next.js proxy route at `/api/showcase` forwards to daemon without auth
- [ ] Dark/light theme toggle works on the page using existing token system
- [ ] Page is accessible without authentication (public route)
- [ ] Showcase config is editable without frontend code changes
- [ ] Page is responsive (mobile, tablet, desktop)
- [ ] Presentation components (hero, cards, stats) are exported for reuse

## Constraints

- Follow existing frontend patterns: `useQuery` for data fetching, Tailwind CSS for styling, Lucide for icons
- Follow existing daemon patterns: FastAPI router, cache reads for stats
- Follow web-api-facade pattern: browser calls Next.js API, Next.js proxies to daemon
- No new dependencies — use what's already in `package.json` and the daemon stack
- No build-time data fetching — all data is runtime from the daemon API

## Risks

- **Daemon unavailable**: Page shows loading/error state. Mitigated by standard error handling pattern from existing proxy routes.
- **Stale stats**: Cache TTLs mean stats may lag by up to 60s. Acceptable for a showcase page.
- **Public exposure**: No auth means anyone with the URL can see the page. This is intentional — showcase content is non-sensitive (project identity, capability descriptions, aggregate stats).

## Data Schema

### Daemon response (`GET /api/showcase`)

```json
{
  "identity": {
    "name": "TeleClaude",
    "tagline": "Multi-computer AI agent orchestration platform",
    "description": "Terminal bridge between UI adapters and AI execution environments.",
    "github": "https://github.com/InstruktAI/TeleClaude",
    "links": [
      { "label": "Documentation", "url": "..." },
      { "label": "Releases", "url": "..." },
      { "label": "License", "url": "..." }
    ]
  },
  "capabilities": [
    {
      "title": "Multi-Computer Orchestration",
      "description": "Manage AI agent sessions across multiple computers via Redis transport."
    },
    {
      "title": "AI Agent Sessions",
      "description": "Launch and supervise Claude, Gemini, and Codex agents in tmux environments."
    }
  ],
  "stats": {
    "computers": 3,
    "active_sessions": 7,
    "projects": 12
  },
  "tech": [
    "Python daemon",
    "Next.js frontend",
    "Redis transport",
    "SQLite persistence",
    "FastAPI",
    "WebSocket real-time"
  ]
}
```

### Showcase config (daemon-side)

Config-driven content stored in `teleclaude.yml` under a `showcase:` section or a standalone `showcase.yml` file. The daemon reads it at startup and merges with live stats at request time.
