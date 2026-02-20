# TUI Markdown Editor & Todo Creation — Design

## Overview

Add inline markdown editing and one-key todo creation to the TUI preparation view. The editor runs as a standalone Textual micro-app in the right tmux pane (same architecture as Glow preview), enabling brain-dump workflows with zero friction.

## Approach

**Approach C: Textual editor subprocess in tmux pane.**

A tiny standalone Textual app (`teleclaude.cli.editor`) provides a `TextArea` with markdown highlighting. It runs in the right tmux pane via the existing `PaneManagerBridge` → `TmuxPaneManager` command pipeline — identical to how Glow is launched for preview. The TUI left panel stays visible and navigable while editing.

### Why this approach

- Reuses existing tmux pane architecture (minimal structural changes)
- Full Textual TextArea features: markdown highlighting, undo/redo, clipboard, soft wrap
- Auto-save on exit is trivial (write before quit)
- Styled consistently (Textual, can share theme detection)
- Todo list stays visible while editing
- ~130 lines for editor + ~30 lines TUI integration

### Rejected alternatives

- **External editor (micro/$EDITOR) in tmux pane**: cheapest (~20 lines) but no auto-save-on-leave, external dependency, styling mismatch.
- **Full-screen Textual Screen overlay**: simplest pure-Textual approach but covers entire left panel — todo list not visible while editing.

## Design

### 1. New todo creation flow

When `n` is pressed in the preparation view:

1. **Slug input modal** — a `ModalScreen` with a single `Input` field. Validates slug format (`^[a-z0-9]+(?:-[a-z0-9]+)*$`) inline. Same modal pattern as `StartSessionModal`.
2. **Scaffold** — calls `create_todo_skeleton()` which now also creates `input.md`.
3. **Auto-open editor** — posts a `DocEditRequest` for the new `input.md`, opening it in the editor in the right tmux pane.
4. **View update** — preparation view refreshes (todo watcher detects new folder), expands the new todo row, cursor lands on `input.md` file row.

### 2. Keybinding scheme (preparation view)

| Key        | On TodoRow                | On TodoFileRow                  |
| ---------- | ------------------------- | ------------------------------- |
| **Enter**  | Expand/collapse (current) | Open editor in right pane (new) |
| **Space**  | No action                 | Preview with Glow (current)     |
| **p**      | Prepare (current)         | —                               |
| **s**      | Start work (current)      | —                               |
| **n**      | Create new todo (new)     | —                               |
| Left/Right | Collapse/expand (current) | —                               |

Action bar updates to: `[Enter] Edit  [Space] Preview  [n] New Todo  [p] Prepare  [s] Start Work`

### 3. Editor micro-app (`teleclaude.cli.editor`)

A standalone Textual app (~100–130 lines):

- **TextArea** with `language="markdown"`, `soft_wrap=True`, line numbers
- **Title bar** showing the file path
- **Keybindings**: `Escape` = save + exit, `Ctrl+S` = explicit save
- **Auto-save on exit**: writes file contents before quitting
- **CLI entry**: `python -m teleclaude.cli.editor <filepath>`
- **Theming**: detects terminal background for dark/light theme

Launched by PaneManagerBridge exactly like Glow — command is `python -m teleclaude.cli.editor /path/to/file.md` instead of `glow -p /path/to/file.md`.

### 4. Scaffold changes

Add `input.md` to `create_todo_skeleton()`. New template at `templates/todos/input.md`:

```markdown
# Input: {slug}

<!-- Brain dump — raw thoughts, ideas, context. Prepare when ready. -->
```

### 5. TUI integration

- **New message**: `DocEditRequest(doc_id, command, title)` — parallel to `DocPreviewRequest`
- **PaneManagerBridge**: handles `on_doc_edit_request` same as `on_doc_preview_request` (stores as `_active_doc_preview` with the editor command)
- **PreparationView**: `action_activate()` on `TodoFileRow` posts `DocEditRequest`
- **PreparationView**: `action_preview_file()` (Space) continues posting `DocPreviewRequest` with Glow
- **New modal**: `CreateTodoModal(ModalScreen[str | None])` with slug input + validation
- **Action bar**: context hints updated for preparation view

### 6. Files to create/modify

**Create:**

- `teleclaude/cli/editor.py` — standalone Textual editor app
- `teleclaude/cli/__main_editor__.py` or use `__main__` in editor module
- `templates/todos/input.md` — input.md template

**Modify:**

- `teleclaude/todo_scaffold.py` — add input.md to scaffold
- `teleclaude/cli/tui/messages.py` — add `DocEditRequest` message
- `teleclaude/cli/tui/pane_bridge.py` — handle `DocEditRequest`
- `teleclaude/cli/tui/views/preparation.py` — new keybinding `n`, edit-on-enter for file rows
- `teleclaude/cli/tui/widgets/modals.py` — add `CreateTodoModal`
- `teleclaude/cli/tui/widgets/action_bar.py` — update preparation hints

## Decisions

- All `.md` files in todo folders are editable (not just input.md)
- Auto-save on leave (navigate away / Escape = saved)
- `Ctrl+S` as explicit save for belt-and-suspenders
- `n` key triggers new todo creation
- Editor runs in tmux pane, not inside the Textual app
