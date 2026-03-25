# web-tui-panels — Input

Build the remaining three admin tabs (Preparation, Config, Jobs) on top of the shell infrastructure established by web-tui-shell. Each tab adds a distinct admin view with its own tree/list components, keyboard shortcuts, modals, and API routes.

## Preparation tab
- Hierarchical tree: Computer -> Project -> Todo -> Files (nested, expandable)
- Computer headers (from configured trusted dirs / computers)
- Project headers per computer
- Todo rows: slug, status badge (pending/icebox/delivered), compact phase tags (B/R/DOR/DEF/F), DOR score, deferrals count
- File rows nested under expanded todos (all non-hidden files under todos/{slug}/, alphabetically)
- Keyboard navigation: ↑/↓ cursor, ←/→ collapse/expand, Enter toggle/open, Space preview, +/- all, n todo, b bug, p prepare, s start, r refine, R remove, f freeze, Shift+↑/↓ move
- API: /api/todos already exists for GET. Need POST (create) and DELETE (remove).

## Jobs tab
- Two sections: "Scheduled Jobs" and "One-shot Jobs"
- Each job row: name, schedule expression or "one-shot", script/command
- Cursor-navigable list
- Keyboard: ↑/↓ cursor, Enter run job
- API: /api/jobs does not exist yet — stub UI until endpoint exists

## Config tab
- 5 subtabs: Adapters, People, Notifications, Environment, Validate
- Adapters: enable/disable and edit per-adapter fields
- People: list people, add/edit (name, email, role)
- Notifications: notification preferences
- Environment: list and edit env vars (masked by default, reveal on click)
- Validate: run config validation, show status per env var
- Keyboard: ↑/↓ navigate, Tab/Shift+Tab cycle subtabs, ←/→ cycle enum values, Enter select/edit, Esc cancel, g guided mode, v validate, r refresh
- API: /api/settings GET/PATCH exists but PATCH is restricted to tts key. Must expand to accept full admin config payloads (adapters, notifications, environment).

## Modals
- New Todo Modal: slug input, validated (lowercase, numbers, hyphens only)
- New Bug Modal: slug input, same validation
- New Project Modal: name, description, path (validated as existing directory)

## Toast notifications
- Fire toasts for: todo created, bug created, prepare dispatched, work dispatched, refine dispatched, todo removed, todo frozen, todo moved, job dispatched, config saved, config validated

## API route additions
- POST /api/todos: create a new todo
- DELETE /api/todos: remove a todo
- POST /api/projects: create a new project (for new project modal)
- PATCH /api/people: update people config
- Expand PATCH /api/settings: accept adapters, notifications, environment payloads (not just tts)

## Constraints
- Stack: Next.js 15, React 19, TypeScript, Tailwind 4
- Component library: shadcn/ui exclusively
- Must use existing daemon API routes; Jobs tab stubs until /api/jobs exists
- Config editing needs admin-only auth gating
- Dark and light mode throughout

## Reference: Existing Code
- Keyboard bindings: frontend/lib/keys/bindings.ts — preparation and config contexts already defined
- API types: frontend/lib/api/types.ts — TodoInfo, ProjectInfo, Settings types exist
- Todos API route: frontend/app/api/todos/route.ts (GET only)
- Settings API route: frontend/app/api/settings/route.ts (PATCH restricted to tts)
- People API route: frontend/app/api/people/route.ts (GET only)
- Projects API route: frontend/app/api/projects/route.ts (GET only)
- Auth guards: frontend/lib/proxy/auth-guards.ts — requireAdmin, requireOwnership
- Daemon proxy: frontend/lib/proxy/daemon-client.ts
- useTodos hook: frontend/lib/hooks/useTodos.ts
