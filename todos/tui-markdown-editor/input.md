# Input: tui-markdown-editor

Add inline markdown editing and one-key todo creation to the TUI preparation view.

## What we want

1. Press `n` in preparation view to create a new todo (slug input popup), then immediately open `input.md` in an editor.
2. Press `Enter` on any file row to edit that file in the right pane.
3. Press `Space` on any file row to preview with Glow (existing behavior).
4. Auto-save on leave (Escape = save + close).

## Approach decided

Standalone Textual micro-app (`teleclaude.cli.editor`) with `TextArea(language="markdown")` running in the right tmux pane via the existing PaneManagerBridge command pipeline. Same architecture as Glow preview, different command.

## Artifacts

- Design doc: `docs/plans/2026-02-20-tui-markdown-editor-design.md`
- Implementation plan: `docs/plans/2026-02-20-tui-markdown-editor-plan.md`
