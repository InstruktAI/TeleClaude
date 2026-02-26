# Demo: config-wizard-redesign

## Validation

```bash
telec todo demo validate config-wizard-redesign
```

```bash
python -m pytest tests/unit/test_config_handlers.py tests/unit/test_tui_config_view.py
```

```bash
rg -n "Not implemented yet" teleclaude/cli/tui/views/config.py teleclaude/cli/tui/config_components/notifications.py && exit 1 || echo "OK: notifications placeholder removed"
```

```bash
make lint
```

## Guided Presentation

1. Open the TUI config tab and show the redesigned hierarchy: grouped adapter sections, status labels (`configured|partial|unconfigured`), and overall completion summary.
2. Navigate to an unset env var, press Enter, edit value inline, save, and show the status/progress update immediately.
3. Re-open edit mode for another field and cancel to show non-destructive behavior.
4. Enter guided mode and walk through the step sequence, showing step index/total and progress changes.
5. Open Notifications and show the actionable summary surface (not placeholder text).
6. Trigger validation from the config surface and show updated pass/fail summary after edits.
