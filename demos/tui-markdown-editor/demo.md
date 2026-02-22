# Demo: TUI Markdown Editor & Todo Creation

## Validation

Verify the editor module is importable and the EditorApp class exists.

```bash
python -c "from teleclaude.cli.editor import EditorApp; print('EditorApp loaded')"
```

Verify the editor CLI entry point responds to --help.

```bash
python -m teleclaude.cli.editor --help
```

Verify the TmuxPaneManager can import the editor launch path.

```bash
python -c "from teleclaude.cli.tui.pane_manager import TmuxPaneManager; print('TmuxPaneManager loaded')"
```

## Guided Presentation

### What to show

Launch `telec` and navigate to the Preparation view. The markdown editor integrates
into the TUI workflow:

- **Launch:** Press `e` on a preparation item to open the editor in the right tmux pane.
- **Editing:** Full markdown syntax highlighting via Textual TextArea. The editor
  supports save (`Ctrl+S`), save-and-quit (`Escape`), and auto-saves on focus loss.
- **View mode:** The `--view` flag opens a read-only markdown preview.
- **Todo creation:** Press `n` in preparation view to create a new todo via the
  inline editor workflow.

### What to narrate

The editor is a standalone Textual micro-app (`teleclaude.cli.editor`) that runs in
the right tmux pane via PaneManagerBridge. This architecture keeps the main TUI
responsive — the editor is a subprocess, not embedded. The auto-save behavior on
focus loss prevents data loss when switching between panes.
