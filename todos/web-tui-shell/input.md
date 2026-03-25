# web-tui-shell — Input

Establish the foundation layout, tab system, and Sessions tab that replaces the current flat sidebar. This is the infrastructure layer that all other tabs build on: 40/60 panel split, tab bar, keyboard navigation infrastructure, context-sensitive footer, toast notifications, and the full Sessions tab with hierarchical tree, activity highlighting, and session actions.

## Layout
- Two-panel layout: left panel = 40% width, right panel = 60%
- Left panel contains: top tab bar (4 tabs) + view content + bottom footer
- Right panel: fixed, shows home page when no session selected; chat view when active session
- No preview pane, no sticky pane, no dynamic layout splitting

## Component Library — shadcn/ui expansion
- Tab bar: Accessible tab component with correct ARIA roles
- Tree panels: Hierarchical tree views with expand/collapse, recursive node rendering, keyboard-driven navigation
- Global keyboard shortcuts: guarded against input/textarea focus, no external hotkey library
- Install additional shadcn/ui primitives: tabs, dialog, scroll-area, badge, tooltip, sonner

## Sessions tab
- Hierarchical tree: Computer -> Project -> Session, AI-to-AI child sessions nest deeper
- Computer header: icon, name, online/offline status badge, total session count
- Project header: icon, project name, truncated path, session count
- Session rows: [N] index badge, agent icon styled per agent design token color, thinking mode, title, subdir slug
- Expand/collapse session row to show detail lines
- Orphaned sessions grouped under synthetic "—" project
- Activity highlighting: full-row, not just dot. From agent_activity WebSocket event, discriminate by event.type field
- Keyboard navigation: ↑/↓ cursor, Enter select+focus, ←/→ expand/collapse, +/- expand/collapse all, n new, R restart, k kill
- Enter on project header opens new session modal pre-filled
- Restart button in right panel header

## Modals
- Migrate NewSessionDialog from custom overlay to shadcn Dialog
- New Session Modal: computer, project, agent (with availability), mode, title, message, session ID fields
- Confirm Modal: title + message + Yes/No/Esc (for kill action)

## Footer
- Fixed at bottom of left panel, always visible
- Context-sensitive keyboard shortcuts for current tab + selected item type
- Each key: <kbd> styled element + description label
- Updates dynamically as cursor moves

## Keyboard infrastructure
- All tree navigation shortcuts fire only when left panel has focus
- Global shortcuts guarded against text input/textarea focus
- Tab switching: 1-4 number keys (same focus guard)
- Esc closes active modal or clears selection

## Toast notifications
- Toast via sonner (shadcn/ui adopted)
- Fire toasts for: session created, session restarted, session ended

## API changes
- POST /api/sessions: forward native_session_id + subdir fields for resume-oriented sessions

## Constraints
- Stack: Next.js 15, React 19, TypeScript, Tailwind 4
- Component library: shadcn/ui exclusively
- Toast: sonner (shadcn/ui adopted)
- Agent colors must match existing design tokens (/lib/theme/tokens.css)
- Dark and light mode throughout
- Must not break existing chat/message view

## Reference: Existing Code
- Current sidebar: frontend/components/sidebar/Sidebar.tsx
- Session list: frontend/components/sidebar/SessionList.tsx
- New session dialog: frontend/components/sidebar/NewSessionDialog.tsx
- Session header: frontend/components/sidebar/SessionHeader.tsx
- Chat layout: frontend/app/(chat)/layout.tsx
- Chat page: frontend/app/(chat)/page.tsx
- Keyboard bindings: frontend/lib/keys/bindings.ts, frontend/lib/keys/types.ts
- WebSocket hooks: frontend/lib/ws/useWebSocket.ts, frontend/lib/ws/useCacheInvalidation.ts
- API types: frontend/lib/api/types.ts
- Design tokens: frontend/lib/theme/tokens.css, frontend/lib/theme/tokens.ts
- Sessions API route: frontend/app/api/sessions/route.ts
