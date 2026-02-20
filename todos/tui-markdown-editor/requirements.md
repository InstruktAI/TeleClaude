# Requirements: tui-markdown-editor

## Goal

Add inline markdown editing and one-key todo creation to the TUI preparation view, enabling zero-friction brain-dump workflows.

## Scope

### In scope

- Standalone Textual editor micro-app (`teleclaude.cli.editor`) with markdown highlighting, auto-save on exit
- `CreateTodoModal` for slug input with validation
- `DocEditRequest` message and PaneManagerBridge wiring
- Updated keybindings: Enter=edit, Space=preview, n=new todo
- `input.md` added to todo scaffold template
- Updated ActionBar hints

### Out of scope

- Live preview (split editor + rendered markdown side by side)
- File creation from within the editor (only edit existing files)
- Editing files outside todo folders
- Syntax highlighting themes beyond Textual defaults

## Success Criteria

- [ ] `n` in preparation view opens slug modal, creates todo, opens input.md in editor
- [ ] `Enter` on any TodoFileRow opens the file in the editor (right tmux pane)
- [ ] `Space` on any TodoFileRow shows Glow preview (unchanged)
- [ ] Editor auto-saves on Escape, explicit Ctrl+S also works
- [ ] `input.md` scaffolded with all new todos
- [ ] All existing tests pass, new tests for scaffold and editor

## Constraints

- Must reuse existing tmux pane architecture (PaneManagerBridge)
- Editor runs as subprocess in tmux pane, not inside the Textual TUI app
- No new Python dependencies (Textual TextArea is built-in)

## Risks

- TextArea markdown language support may lack tree-sitter on some systems (graceful fallback to plain text)
