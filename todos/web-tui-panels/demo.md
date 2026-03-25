# Demo: web-tui-panels

## Medium

Web browser — open the TeleClaude web TUI at localhost:3000.

## What the user observes

### Tab navigation

1. The header area shows a tab bar with 4 tabs: Sessions, Preparation,
   Configuration, Jobs.
2. Sessions tab is active by default.
3. Pressing `2` switches to Preparation view. Tab bar updates to highlight
   Preparation.
4. Pressing `3` switches to Configuration. Pressing `4` switches to Jobs.
   Pressing `1` returns to Sessions.
5. Clicking a tab also switches views.
6. Switching away from a view and back preserves its state (scroll position,
   selected items).

### Preparation view

1. The tree displays Computer nodes at the top level.
2. Expanding a computer shows its projects. Expanding a project shows todos.
3. Todo rows show: slug, colored status badge, compact phase tags (B/R/DOR/DEF/F),
   DOR score, deferrals count.
4. Expanding a todo shows its file list alphabetically.
5. Arrow keys navigate the cursor. Left/right expand/collapse. +/- toggle all.
6. Pressing `n` opens the New Todo modal. Entering a valid slug and submitting
   creates a todo (toast confirms).
7. Pressing `p` on a focused todo dispatches prepare (toast confirms).
8. Pressing `R` on a focused todo shows "Operation unavailable" toast.

### Configuration view

1. Non-admin user sees "Admin access required" message.
2. Admin user sees 5 subtabs: Adapters, People, Notifications, Environment,
   Validate.
3. Tab/Shift+Tab cycles between subtabs.
4. People subtab lists configured people with name, email, role.
5. Environment subtab shows masked values; clicking reveals them.

### Jobs view

1. Jobs are listed in two sections: Scheduled and One-shot.
2. Each row shows name, schedule, type, last run, status.
3. Arrow keys navigate. Enter triggers the selected job (toast confirms).

### Toast notifications

1. Creating a todo shows a success toast.
2. Triggering a job shows a success toast.
3. Dispatching prepare shows a success toast.
4. Failed operations show a destructive (red) toast.
5. Toasts auto-dismiss after ~4 seconds.

### Theme

1. Toggle dark mode. All new views render correctly with no invisible text
   or broken contrast.

## Validation

```bash
# Verify the web TUI builds without errors
cd frontend && pnpm build
```

```bash
# Verify tests pass
cd frontend && pnpm test:cli
```

```bash
# Verify type checking passes
cd frontend && pnpm tsc --noEmit
```
