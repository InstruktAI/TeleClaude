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

Launch `telec` and navigate to the Preparation view. Press `e` on a preparation item to open the editor in the right tmux pane. Full markdown syntax highlighting via Textual TextArea — save with `Ctrl+S`, save-and-quit with `Escape`. The editor auto-saves on focus loss to prevent data loss when switching panes.

The editor is a standalone Textual micro-app (`teleclaude.cli.editor`) that runs as a subprocess in the right tmux pane via PaneManagerBridge. This architecture keeps the main TUI responsive — the editor is not embedded.

Try `--view` flag for read-only markdown preview. Then press `n` in preparation view to create a new todo via the inline editor workflow.
