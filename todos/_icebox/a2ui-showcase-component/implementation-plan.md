# Implementation Plan: a2ui-showcase-component

## Overview

Three layers: daemon endpoint, Next.js proxy, React page. Each layer follows established patterns already proven in the codebase.

## Tasks

### Task 1: Daemon showcase endpoint

**What:** Add an inline endpoint in `_setup_routes()` that serves showcase content as JSON.

**Files:**

- Edit `teleclaude/api_server.py` — add `GET /api/showcase` route inside `_setup_routes()` (same pattern as `/computers`, `/sessions`)

**Approach:**

- Define as an inline route in `_setup_routes()` — this is required because the endpoint needs `self.cache` access, and all cache-reading endpoints use closures over `self` (see `/computers` at line ~835, `/sessions` at line ~360). Separate router files like `data_routes.py` do NOT have cache access.
- Read static identity/capability data from a `showcase` section in `teleclaude.yml` (or fallback defaults if section absent)
- Read live stats from `DaemonCache`: `len(self.cache.get_computers())`, `len(self.cache.get_sessions())`, `len(self.cache.get_projects())`
- Merge and return as structured JSON matching the schema in requirements
- No authentication — this endpoint is public

**Verification:** `curl --unix-socket /tmp/teleclaude-api.sock http://localhost/api/showcase` returns valid JSON with identity, capabilities, stats, and tech fields.

### Task 2: Showcase config schema

**What:** Define the showcase config section in the daemon config schema.

**Files:**

- Edit `teleclaude/config/schema.py` (or equivalent config model) — add `ShowcaseConfig` model
- Edit config validation to accept the new section

**Approach:**

- Pydantic model with optional fields: `name`, `tagline`, `description`, `github`, `links`, `capabilities`, `tech`
- All fields have sensible defaults so showcase works without explicit config
- Capabilities and tech are lists of objects/strings

**Verification:** Daemon starts cleanly with and without `showcase:` section in config.

### Task 3: Next.js API proxy route

**What:** Add a proxy route handler that forwards to the daemon showcase endpoint.

**Files:**

- Create `frontend/app/api/showcase/route.ts`

**Approach:**

- Follow exact pattern from `frontend/app/api/computers/route.ts`
- `GET` handler only
- No `auth()` check — this is a public endpoint
- `daemonRequest({ method: "GET", path: "/api/showcase" })`
- Standard error handling: 503 if daemon unreachable

**Verification:** `curl http://localhost:3000/api/showcase` returns the same JSON as the daemon endpoint.

### Task 4: Showcase page — data fetching and layout

**What:** Build the `/showcase` page as a client component with React Query data fetching.

**Files:**

- Create `frontend/app/showcase/page.tsx` — main page component
- Create `frontend/app/showcase/layout.tsx` — minimal layout (QueryProvider, no auth check)

**Approach:**

- Layout wraps children in `QueryProvider` (no `WebSocketProvider` needed — static data)
- Page uses `useQuery({ queryKey: ["showcase"], queryFn: fetchShowcase })` with a 60s refetch interval for stats
- Responsive grid layout: hero top, capabilities middle, stats + tech + links bottom
- Loading skeleton while data fetches
- Error state if daemon unreachable

**Verification:** Navigate to `/showcase` — page renders with content from daemon.

### Task 5: Presentation components

**What:** Build the reusable UI components for the showcase layout.

**Files:**

- Create `frontend/components/showcase/Hero.tsx`
- Create `frontend/components/showcase/CapabilityCard.tsx`
- Create `frontend/components/showcase/StatBlock.tsx`
- Create `frontend/components/showcase/LinkList.tsx`
- Create `frontend/components/showcase/TechBadge.tsx`

**Approach:**

- **Hero**: Project name (large), tagline, description, GitHub link button. Full-width section with gradient or subtle background.
- **CapabilityCard**: Icon + title + description. Responsive grid (1 col mobile, 2 col tablet, 3 col desktop). Follow `ComputerCard` pattern (rounded-xl border, bg-card).
- **StatBlock**: Large number + label. Horizontal row of 3 blocks. Live-updating from API data.
- **LinkList**: Simple list of labeled links with external-link icons.
- **TechBadge**: Pill-shaped badges for technology names.
- All components use Tailwind classes referencing CSS custom property tokens (`text-primary`, `bg-card`, `border`, `text-muted-foreground`).
- All components accept data props (no internal fetching) — the page component owns the data.

**Verification:** Components render correctly with mock data. Visual check across viewport sizes.

### Task 6: Theme toggle

**What:** Add a dark/light theme toggle on the showcase page.

**Files:**

- Edit `frontend/app/showcase/page.tsx` — add toggle control
- Reuse `frontend/lib/theme/css-variables.ts` — `injectCSSVariables(mode)`

**Approach:**

- Local state: `useState<ThemeMode>` initialized from `detectThemeMode()`
- Toggle button in the top-right corner (sun/moon icon from Lucide)
- On toggle: call `injectCSSVariables(newMode)`, update state
- All showcase components automatically restyle via CSS custom properties — no prop changes needed

**Verification:** Toggle switches between dark and light themes. All components restyle correctly.

### Task 7: Update web-api-facade doc

**What:** Add the showcase route to the public contract table.

**Files:**

- Edit `docs/project/design/architecture/web-api-facade.md` — add row to route table

**Approach:**

- Add: `GET /api/showcase | proxy | none | daemon showcase endpoint`
- This is the first public (no auth) route in the table — note the precedent.

**Verification:** Doc accurately reflects the new route.

## Build Order

```
Task 1 (daemon endpoint) + Task 2 (config schema) → can run in parallel
Task 3 (proxy route) → depends on Task 1
Task 4 (page) + Task 5 (components) → depend on Task 3
Task 6 (theme toggle) → depends on Task 4
Task 7 (doc update) → independent, can run anytime
```

Linear path for a single builder: 1 → 2 → 3 → 5 → 4 → 6 → 7

## Commit Strategy

- One commit per task or per logical group (tasks 1+2 together, tasks 4+5 together)
- Final commit for doc update
