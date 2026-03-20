# Input: web-tui-parity

<!-- Brain dump — raw thoughts, ideas, context. Prepare when ready. -->

## User Intent

The web frontend must be a full admin environment with complete TUI parity across all four tabs. Right now the web only shows a flat sidebar list for consumers. The TUI has:

- **Sessions tab**: Computers → Projects → Sessions hierarchy, full-row highlight, all keyboard shortcuts (↑↓, Enter, ←→, +/-, n, R, k)
- **Preparation tab**: Computer → Project → Todo → Files hierarchy, full todo lifecycle (n, b, p, s, r, R, f, Shift+↑↓)
- **Jobs tab**: Scheduled + one-shot jobs, run with Enter
- **Config tab**: 5 subtabs (Adapters, People, Notifications, Environment, Validate), guided mode, validation
- **Context-sensitive footer** showing active keybindings per view and selected node type
- **40% left panel** with tab bar, scrollable tree content, fixed footer
- **Sonner toasts** for all dispatched actions (no spinners)
- **All modals** using shadcn Dialog primitive with proper focus + Esc handling

The web frontend is the remote admin console for people not running the TUI locally. Full parity — adapted for browser (no tmux, no sticky panes, click-to-select instead of preview).

## Reference: TUI Implementation

- Main TUI entry: `teleclaude/cli/tui/app.py`
- Sessions view: `teleclaude/cli/tui/views/sessions.py`
- Tree building: `teleclaude/cli/tui/tree.py`
- Session row widget: `teleclaude/cli/tui/widgets/session_row.py`
- Computer header: `teleclaude/cli/tui/widgets/computer_header.py`
- Project header: `teleclaude/cli/tui/widgets/project_header.py`
- Activity highlights: `teleclaude/cli/tui/views/sessions_highlights.py`
- Theme/colors: `teleclaude/cli/tui/theme.py`

## Reference: Web Frontend

- Dashboard: `frontend/app/dashboard/`
- Sidebar: `frontend/components/sidebar/`
- Design tokens: `frontend/lib/theme/tokens.css`
- WebSocket provider: `frontend/lib/ws/WebSocketProvider.tsx`
- API types: `frontend/lib/api/types.ts`
